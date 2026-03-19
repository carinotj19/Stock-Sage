from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    ForecastRun,
    InventoryBalance,
    Product,
    ReorderRecommendation,
    SalesItem,
    SalesTransaction,
    SkuForecast,
    StockMovement,
    Supplier,
)
from app.db.session import SessionLocal
from app.ml.model_registry import CandidateScore
from app.ml.predict import (
    ForecastDataQuality,
    estimate_censored_sales_dates,
    forecast_product_daily_units_with_diagnostics,
)
from app.services.reorder_service import ReorderService

MIN_ACTIONABLE_CONFIDENCE = 0.55
MAX_ACTIONABLE_WMAPE_PCT = 45.0
MIN_ACTIONABLE_HISTORY_DAYS = 30
MIN_ACTIONABLE_NON_ZERO_DAYS = 10
SPARSE_ANALOG_BLEND = 0.35
COLD_START_ANALOG_BLEND = 0.55
MAX_HISTORY_LAG_DAYS = 14
MAX_DAYS_SINCE_LAST_SALE = 30
HARD_GATE_REASONS = {"sparse_sales", "few_non_zero_days", "wmape_unavailable", "no_recent_sales_30d"}
BASELINE_FALLBACK_REASON = "baseline_not_beaten"
CHAMPION_LOCK_FALLBACK_REASON = "baseline_champion_locked"
WMAPE_FALLBACK_REASON = "wmape_high"
STALE_HISTORY_FALLBACK_REASON = "stale_history"
NON_MATURE_GUARDRAIL_REASON = "non_mature_guardrail"
BASELINE_FALLBACK_CONFIDENCE_FLOOR = 0.55
BASELINE_FALLBACK_CONFIDENCE_CEIL = 0.68
HIGH_CONFIDENCE_MIN = 0.70
MARGIN_THRESHOLD_BY_TIER = {
    "mature": 0.90,
    "developing": 0.95,
    "sparse": 0.98,
    "cold_start": 1.00,
}
BASELINE_MARGIN_TOLERANCE_WMAPE_PCT_FLOOR = 2.0
BASELINE_MARGIN_TOLERANCE_WMAPE_PCT_CAP = 6.0
MATURE_BASELINE_MARGIN_TOLERANCE_WMAPE_PCT_FLOOR = 3.5
DATA_QA_RECENT_SALES_DAYS = 30
DATA_QA_STALE_HISTORY_DAYS = 14
DATA_QA_CRITICAL_ISSUES = {"no_sales_history", "all_zero_history"}
DATA_QA_MODES = {"off", "warn", "strict"}
MATURE_HISTORY_DAYS = 42
MATURE_NON_ZERO_DAYS = 12
MATURE_NON_ZERO_RATIO = 0.18
MATURE_MAX_HISTORY_LAG_DAYS = 14
MATURE_MIN_TRAILING_30_NON_ZERO_DAYS = 2
LEAD_TIME_BACKTEST_MAX_WINDOWS = 4
LEAD_TIME_BACKTEST_MIN_TRAIN_DAYS = 14
BASELINE_STRONG_LOSS_MIN_WINDOWS = 3
BASELINE_STRONG_LOSS_MAX_WIN_RATIO = 0.34
CHAMPION_LOCK_MIN_WINDOWS = 4
CHAMPION_LOCK_MAX_WIN_RATIO = 0.25


def _load_sales_history(db: Session, product_id: int) -> pd.DataFrame:
    statement = (
        select(
            func.date(SalesTransaction.sold_at).label("sale_date"),
            func.sum(SalesItem.qty).label("units"),
        )
        .join(SalesTransaction, SalesItem.sales_transaction_id == SalesTransaction.id)
        .where(SalesItem.product_id == product_id)
        .group_by("sale_date")
        .order_by("sale_date")
    )
    rows = db.execute(statement).all()
    if not rows:
        return pd.DataFrame(columns=["date", "units"])

    return pd.DataFrame(
        [{"date": row.sale_date, "units": float(row.units or 0)} for row in rows],
        columns=["date", "units"],
    )


def _load_stock_movements(db: Session, product_id: int) -> pd.DataFrame:
    statement = (
        select(
            StockMovement.occurred_at.label("occurred_at"),
            StockMovement.qty_delta.label("qty_delta"),
            StockMovement.movement_type.label("movement_type"),
        )
        .where(StockMovement.product_id == product_id)
        .order_by(StockMovement.occurred_at.asc())
    )
    rows = db.execute(statement).all()
    if not rows:
        return pd.DataFrame(columns=["occurred_at", "qty_delta", "movement_type"])

    return pd.DataFrame(
        [
            {
                "occurred_at": row.occurred_at,
                "qty_delta": float(row.qty_delta or 0),
                "movement_type": str(row.movement_type or ""),
            }
            for row in rows
        ],
        columns=["occurred_at", "qty_delta", "movement_type"],
    )


def _dense_daily_units_series(sales_history: pd.DataFrame) -> pd.Series:
    if sales_history.empty:
        return pd.Series(dtype=float)
    frame = sales_history.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    grouped = frame.groupby("date", as_index=True)["units"].sum().sort_index().astype(float)
    if grouped.empty:
        return pd.Series(dtype=float)
    full_dates = pd.date_range(grouped.index.min(), grouped.index.max(), freq="D")
    dense = grouped.reindex(full_dates, fill_value=0.0).astype(float)
    dense.name = "units"
    return dense


def _sales_recency_days(sales_history: pd.DataFrame) -> tuple[int | None, int | None]:
    if sales_history.empty:
        return (None, None)
    frame = sales_history.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    if frame.empty:
        return (None, None)
    last_sale_ts = frame["date"].max()
    if pd.isna(last_sale_ts):
        return (None, None)
    today = pd.Timestamp.utcnow().date()
    last_sale_date = pd.Timestamp(last_sale_ts).date()
    lag_days = int((today - last_sale_date).days)
    return (lag_days, lag_days)


def _trailing_30_non_zero_days(sales_history: pd.DataFrame) -> int:
    dense = _dense_daily_units_series(sales_history)
    if dense.empty:
        return 0
    return int((dense.tail(30) > 0.0).sum())


def _is_mature_for_decisioning(
    quality: ForecastDataQuality,
    sales_history: pd.DataFrame,
    *,
    history_lag_days: int | None,
) -> bool:
    trailing_30_non_zero_days = _trailing_30_non_zero_days(sales_history)
    return (
        quality.history_days >= MATURE_HISTORY_DAYS
        and quality.non_zero_days >= MATURE_NON_ZERO_DAYS
        and quality.non_zero_ratio >= MATURE_NON_ZERO_RATIO
        and history_lag_days is not None
        and history_lag_days <= MATURE_MAX_HISTORY_LAG_DAYS
        and trailing_30_non_zero_days >= MATURE_MIN_TRAILING_30_NON_ZERO_DAYS
    )


def _apply_non_mature_guardrail(
    reason_tokens: set[str],
    *,
    action: str,
    quality: ForecastDataQuality,
    sales_history: pd.DataFrame,
    history_lag_days: int | None,
) -> tuple[set[str], str]:
    if action != "none":
        return reason_tokens, action
    if _is_mature_for_decisioning(quality, sales_history, history_lag_days=history_lag_days):
        return reason_tokens, action
    next_tokens = set(reason_tokens)
    next_tokens.add(NON_MATURE_GUARDRAIL_REASON)
    return next_tokens, _recommendation_action(next_tokens)


def _apply_champion_lock_guardrail(
    reason_tokens: set[str],
    *,
    action: str,
    lead_time_model_win_count: int | None,
    lead_time_windows_evaluated: int | None,
) -> tuple[set[str], str]:
    if action != "none":
        return reason_tokens, action
    windows = int(lead_time_windows_evaluated or 0)
    if windows < CHAMPION_LOCK_MIN_WINDOWS:
        return reason_tokens, action
    win_ratio = _baseline_win_ratio(lead_time_model_win_count, lead_time_windows_evaluated)
    if win_ratio is None or win_ratio > CHAMPION_LOCK_MAX_WIN_RATIO:
        return reason_tokens, action
    next_tokens = set(reason_tokens)
    next_tokens.add(CHAMPION_LOCK_FALLBACK_REASON)
    return next_tokens, _recommendation_action(next_tokens)


def _parse_qa_mode(value: str | None) -> str:
    mode = (value or "warn").strip().lower()
    if mode not in DATA_QA_MODES:
        raise ValueError(f"qa_mode must be one of {sorted(DATA_QA_MODES)}")
    return mode


def _evaluate_data_quality_precheck(
    products: list[Product],
    sales_histories: dict[int, pd.DataFrame],
) -> dict[str, object]:
    today = pd.Timestamp.utcnow().normalize().date()
    issue_counts: Counter[str] = Counter()
    sku_rows: list[dict[str, object]] = []
    critical_skus = 0
    warning_skus = 0

    for product in products:
        history = sales_histories.get(product.id, pd.DataFrame(columns=["date", "units"]))
        dense = _dense_daily_units_series(history)
        history_days = int(len(dense))
        non_zero_days = int((dense > 0.0).sum()) if history_days > 0 else 0
        non_zero_ratio = float(non_zero_days / history_days) if history_days > 0 else 0.0

        last_history_date = dense.index.max().date() if history_days > 0 else None
        last_non_zero_date = dense[dense > 0.0].index.max().date() if non_zero_days > 0 else None
        days_since_last_sale = (today - last_non_zero_date).days if last_non_zero_date is not None else None
        history_lag_days = (today - last_history_date).days if last_history_date is not None else None
        trailing_30_non_zero_days = int((dense.tail(30) > 0.0).sum()) if history_days > 0 else 0

        issues: list[str] = []
        if history_days == 0:
            issues.append("no_sales_history")
        if history_days > 0 and non_zero_days == 0:
            issues.append("all_zero_history")
        if 0 < history_days < MIN_ACTIONABLE_HISTORY_DAYS:
            issues.append("short_history")
        if 0 < history_days and non_zero_days < MIN_ACTIONABLE_NON_ZERO_DAYS:
            issues.append("few_non_zero_days")
        if 0 < history_days and non_zero_ratio < 0.08:
            issues.append("sparse_history_ratio")
        if days_since_last_sale is not None and days_since_last_sale > DATA_QA_RECENT_SALES_DAYS:
            issues.append("no_recent_sales_30d")
        if history_lag_days is not None and history_lag_days > DATA_QA_STALE_HISTORY_DAYS:
            issues.append("stale_history_window")
        if history_days > 0 and trailing_30_non_zero_days == 0:
            issues.append("zero_recent_30d")

        issue_counts.update(issues)
        critical_tokens = [issue for issue in issues if issue in DATA_QA_CRITICAL_ISSUES]
        if critical_tokens:
            severity = "critical"
            critical_skus += 1
        elif issues:
            severity = "warning"
            warning_skus += 1
        else:
            severity = "ok"

        sku_rows.append(
            {
                "sku": product.sku,
                "product_id": product.id,
                "history_days": history_days,
                "non_zero_days": non_zero_days,
                "non_zero_ratio": round(non_zero_ratio, 4),
                "trailing_30_non_zero_days": trailing_30_non_zero_days,
                "last_history_date": last_history_date.isoformat() if last_history_date else None,
                "last_non_zero_sale_date": last_non_zero_date.isoformat() if last_non_zero_date else None,
                "days_since_last_sale": days_since_last_sale,
                "history_lag_days": history_lag_days,
                "severity": severity,
                "issues": issues,
            }
        )

    summary = {
        "sku_count": len(products),
        "critical_skus": critical_skus,
        "warning_skus": warning_skus,
        "issue_type_count": len(issue_counts),
        "issue_counts": dict(sorted(issue_counts.items())),
    }
    return {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "summary": summary,
        "rows": sku_rows,
    }


def _write_data_quality_report(run_id: int, payload: dict[str, object]) -> Path:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"forecast_data_quality_run{run_id}.json"
    report_payload = {"run_id": run_id, **payload}
    path.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _daily_rate_for_analog_prior(sales_history: pd.DataFrame) -> float | None:
    dense = _dense_daily_units_series(sales_history)
    if dense.empty:
        return None
    history_days = len(dense)
    non_zero_days = int((dense > 0.0).sum())
    if history_days < MIN_ACTIONABLE_HISTORY_DAYS or non_zero_days < MIN_ACTIONABLE_NON_ZERO_DAYS:
        return None
    recent = dense.tail(min(90, history_days))
    rate = float(recent.mean())
    return rate if rate > 0.0 else None


def _build_analog_daily_priors(
    products: list[Product],
    sales_histories: dict[int, pd.DataFrame],
) -> dict[int, float]:
    category_rates: dict[str, list[float]] = {}
    supplier_rates: dict[int, list[float]] = {}
    global_rates: list[float] = []

    for product in products:
        rate = _daily_rate_for_analog_prior(sales_histories.get(product.id, pd.DataFrame()))
        if rate is None:
            continue
        global_rates.append(rate)
        category = (product.category or "").strip().lower()
        if category:
            category_rates.setdefault(category, []).append(rate)
        if product.supplier_id is not None:
            supplier_rates.setdefault(product.supplier_id, []).append(rate)

    global_prior = float(np.median(global_rates)) if global_rates else None
    priors: dict[int, float] = {}
    for product in products:
        category = (product.category or "").strip().lower()
        if category and category in category_rates and category_rates[category]:
            priors[product.id] = float(np.median(category_rates[category]))
            continue
        if product.supplier_id is not None and product.supplier_id in supplier_rates and supplier_rates[product.supplier_id]:
            priors[product.id] = float(np.median(supplier_rates[product.supplier_id]))
            continue
        if global_prior is not None:
            priors[product.id] = global_prior

    return {product_id: float(max(rate, 0.0)) for product_id, rate in priors.items() if rate > 0.0}


def _current_stock(db: Session, product_id: int) -> int:
    balance = db.get(InventoryBalance, product_id)
    return balance.on_hand_qty if balance else 0


def _lead_time_days(db: Session, product: Product) -> int:
    if product.supplier_id is None:
        return 7
    supplier = db.get(Supplier, product.supplier_id)
    if supplier is None:
        return 7
    return max(1, supplier.lead_time_days_default)


def _resolved_data_tier(quality: ForecastDataQuality) -> str:
    tier = quality.data_tier
    if tier != "auto":
        return tier
    if quality.status == "insufficient_history":
        return "cold_start"
    if quality.status == "sparse_sales":
        return "sparse"
    return "developing"


def _margin_threshold_for_tier(tier: str) -> float:
    return float(MARGIN_THRESHOLD_BY_TIER.get(tier, MARGIN_THRESHOLD_BY_TIER["developing"]))


def _baseline_margin_shortfall_wmape_pct(
    lead_time_wmape_pct: float,
    lead_time_baseline_wmape_pct: float,
    tier: str,
) -> float:
    threshold_ratio = _margin_threshold_for_tier(tier)
    required_wmape = lead_time_baseline_wmape_pct * threshold_ratio
    return float(lead_time_wmape_pct - required_wmape)


def _baseline_margin_tolerance_wmape_pct(lead_time_baseline_wmape_pct: float, tier: str) -> float:
    if tier in {"sparse", "cold_start"}:
        ratio = 0.04
        floor = BASELINE_MARGIN_TOLERANCE_WMAPE_PCT_FLOOR
    elif tier == "mature":
        ratio = 0.035
        floor = MATURE_BASELINE_MARGIN_TOLERANCE_WMAPE_PCT_FLOOR
    else:
        ratio = 0.03
        floor = BASELINE_MARGIN_TOLERANCE_WMAPE_PCT_FLOOR
    scaled = float(lead_time_baseline_wmape_pct) * ratio
    return float(
        min(
            BASELINE_MARGIN_TOLERANCE_WMAPE_PCT_CAP,
            max(floor, scaled),
        )
    )


def _baseline_win_ratio(
    model_win_count: int | None,
    windows_evaluated: int | None,
) -> float | None:
    if model_win_count is None or windows_evaluated is None:
        return None
    windows = int(windows_evaluated)
    if windows <= 0:
        return None
    wins = max(0, min(int(model_win_count), windows))
    return float(wins / windows)


def _is_strong_baseline_loss(
    model_win_count: int | None,
    windows_evaluated: int | None,
) -> bool:
    win_ratio = _baseline_win_ratio(model_win_count, windows_evaluated)
    if win_ratio is None:
        # Backward-compatible behavior when no multi-window stats are provided.
        return True
    windows = int(windows_evaluated or 0)
    if windows <= 1:
        return win_ratio <= 0.0
    if windows < BASELINE_STRONG_LOSS_MIN_WINDOWS:
        return win_ratio <= 0.0
    return win_ratio <= BASELINE_STRONG_LOSS_MAX_WIN_RATIO


def _weighted_mape_pct(actual: list[float], predicted: list[float]) -> float | None:
    if not actual:
        return None
    denominator = float(sum(abs(value) for value in actual))
    if denominator <= 0:
        return None
    numerator = float(sum(abs(a - p) for a, p in zip(actual, predicted)))
    return (numerator / denominator) * 100.0


def _apply_analog_prior_fallback(
    forecast_frame: pd.DataFrame,
    quality: ForecastDataQuality,
    analog_daily_prior: float | None,
) -> bool:
    if analog_daily_prior is None or analog_daily_prior <= 0:
        return False
    if quality.data_tier not in {"sparse", "cold_start"}:
        return False

    blend = COLD_START_ANALOG_BLEND if quality.data_tier == "cold_start" else SPARSE_ANALOG_BLEND
    base_pred = forecast_frame["predicted_units"].astype(float).to_numpy()
    lower = forecast_frame["lower_ci"].astype(float).to_numpy()
    upper = forecast_frame["upper_ci"].astype(float).to_numpy()
    prior = np.full(len(base_pred), float(analog_daily_prior), dtype=float)

    blended = ((1.0 - blend) * base_pred) + (blend * prior)
    lower_ratio = np.divide(lower, np.maximum(base_pred, 1e-6))
    upper_ratio = np.divide(upper, np.maximum(base_pred, 1e-6))
    lower_ratio = np.clip(lower_ratio, 0.10, 1.0)
    upper_ratio = np.clip(upper_ratio, 1.0, 2.5)

    forecast_frame["predicted_units"] = np.maximum(blended, 0.0)
    forecast_frame["lower_ci"] = np.maximum(blended * lower_ratio, 0.0)
    forecast_frame["upper_ci"] = np.maximum(blended * upper_ratio, 0.0)
    return True


def _lead_time_operational_backtest(
    sales_history: pd.DataFrame,
    stock_movements: pd.DataFrame,
    lead_time_days: int,
    *,
    analog_daily_prior: float | None = None,
) -> tuple[float | None, float | None, int, int]:
    if sales_history.empty:
        return (None, None, 0, 0)

    history = sales_history.copy()
    history["date"] = pd.to_datetime(history["date"]).dt.normalize()
    history = history.sort_values("date").reset_index(drop=True)
    horizon = max(3, min(14, int(lead_time_days)))
    if len(history) < horizon + LEAD_TIME_BACKTEST_MIN_TRAIN_DAYS:
        return (None, None, 0, 0)

    censored_dates = estimate_censored_sales_dates(
        history[["date", "units"]],
        stock_movements=stock_movements,
    )
    model_scores: list[float] = []
    baseline_scores: list[float] = []
    model_win_count = 0

    for window_index in range(LEAD_TIME_BACKTEST_MAX_WINDOWS):
        holdout_end = len(history) - (window_index * horizon)
        holdout_start = holdout_end - horizon
        if holdout_start <= 0:
            break

        train = history.iloc[:holdout_start][["date", "units"]].copy()
        holdout = history.iloc[holdout_start:holdout_end][["date", "units"]].copy()
        if len(train) < LEAD_TIME_BACKTEST_MIN_TRAIN_DAYS or holdout.empty:
            continue

        train_stock_movements = stock_movements
        if not stock_movements.empty and "occurred_at" in stock_movements.columns:
            cutoff = pd.to_datetime(train["date"]).max()
            movement_dates = pd.to_datetime(stock_movements["occurred_at"]).dt.normalize()
            train_stock_movements = stock_movements.loc[movement_dates <= cutoff].copy()

        backtest_result = forecast_product_daily_units_with_diagnostics(
            train,
            horizon_days=horizon,
            lead_time_days=lead_time_days,
            stock_movements=train_stock_movements,
        )
        forecast_frame = backtest_result.forecast_frame.copy()
        _apply_analog_prior_fallback(
            forecast_frame,
            backtest_result.diagnostics.quality,
            analog_daily_prior,
        )

        predicted = forecast_frame["predicted_units"].astype(float).tolist()
        actual = holdout["units"].astype(float).tolist()
        holdout_dates = pd.to_datetime(holdout["date"]).dt.normalize().tolist()
        if censored_dates:
            keep_mask = [date_value not in censored_dates for date_value in holdout_dates]
            actual = [value for value, keep in zip(actual, keep_mask) if keep]
            predicted = [value for value, keep in zip(predicted, keep_mask) if keep]

        horizon_size = min(len(actual), len(predicted))
        if horizon_size == 0:
            continue
        actual = actual[:horizon_size]
        predicted = predicted[:horizon_size]

        trailing_window = train["units"].tail(min(7, len(train)))
        baseline_level = float(trailing_window.mean()) if not trailing_window.empty else 0.0
        baseline_pred = [baseline_level] * horizon_size

        model_wmape = _weighted_mape_pct(actual, predicted)
        baseline_wmape = _weighted_mape_pct(actual, baseline_pred)
        if model_wmape is None or baseline_wmape is None:
            continue

        model_scores.append(float(model_wmape))
        baseline_scores.append(float(baseline_wmape))
        if float(model_wmape) <= float(baseline_wmape):
            model_win_count += 1

    windows_evaluated = len(model_scores)
    if windows_evaluated == 0:
        return (None, None, 0, 0)

    return (
        float(np.mean(model_scores)),
        float(np.mean(baseline_scores)),
        int(model_win_count),
        int(windows_evaluated),
    )


def _baseline_forecast_frame(sales_history: pd.DataFrame, template_frame: pd.DataFrame) -> pd.DataFrame:
    trailing_values = (
        sales_history.sort_values("date")["units"].astype(float).tail(7).to_numpy()
        if not sales_history.empty
        else np.array([], dtype=float)
    )
    baseline_level = float(np.mean(trailing_values)) if trailing_values.size > 0 else 0.0
    baseline_level = max(baseline_level, 0.0)
    lower = max(0.0, baseline_level * 0.8)
    upper = baseline_level * 1.2
    horizon_days = len(template_frame)
    frame = template_frame.copy()
    frame["predicted_units"] = [baseline_level] * horizon_days
    frame["lower_ci"] = [lower] * horizon_days
    frame["upper_ci"] = [upper] * horizon_days
    return frame


def _calibrate_confidence(
    score: CandidateScore,
    quality: ForecastDataQuality,
    *,
    lead_time_wmape_pct: float | None = None,
    lead_time_baseline_wmape_pct: float | None = None,
    lead_time_model_win_count: int | None = None,
    lead_time_windows_evaluated: int | None = None,
    history_lag_days: int | None = None,
    days_since_last_sale: int | None = None,
) -> float:
    # Confidence is calibrated from empirical rolling backtest accuracy and stability.
    historical_wmape = score.wmape_pct if score.wmape_pct is not None else 95.0
    wmape = historical_wmape
    if lead_time_wmape_pct is not None:
        wmape = (0.65 * float(lead_time_wmape_pct)) + (0.35 * historical_wmape)
    wmape_std = score.wmape_std_pct if score.wmape_std_pct is not None else 25.0
    mape = score.mape_pct if score.mape_pct is not None else max(wmape, 95.0)
    windows = max(1, int(score.windows_evaluated))

    effective_error = (0.65 * wmape) + (0.35 * mape) + (0.55 * wmape_std)
    confidence = 1.0 - (effective_error / 155.0)

    # Penalize low backtest sample count to avoid overconfident unstable models.
    if windows < 2:
        confidence -= 0.12
    elif windows < 3:
        confidence -= 0.06

    tier = _resolved_data_tier(quality)

    if tier == "cold_start":
        confidence -= 0.25
    elif tier == "sparse":
        confidence -= 0.10
    elif tier == "developing":
        confidence -= 0.04

    if quality.non_zero_ratio < 0.15:
        confidence -= 0.05
    if quality.suspected_stockout_days > 0:
        confidence -= 0.05
    if quality.capped_outlier_days > max(2, int(0.1 * max(quality.history_days, 1))):
        confidence -= 0.05

    if history_lag_days is not None and history_lag_days > MAX_HISTORY_LAG_DAYS:
        confidence -= 0.10
        confidence = min(confidence, 0.62)
    if days_since_last_sale is not None and days_since_last_sale > MAX_DAYS_SINCE_LAST_SALE:
        confidence -= 0.20
        confidence = min(confidence, 0.49)

    if lead_time_wmape_pct is not None:
        if lead_time_wmape_pct <= MAX_ACTIONABLE_WMAPE_PCT:
            confidence += 0.04
        elif lead_time_wmape_pct >= (MAX_ACTIONABLE_WMAPE_PCT * 1.5):
            confidence -= 0.08
    if lead_time_wmape_pct is not None and lead_time_baseline_wmape_pct is not None:
        threshold_ratio = _margin_threshold_for_tier(tier)
        if lead_time_baseline_wmape_pct > 0:
            ratio = lead_time_wmape_pct / lead_time_baseline_wmape_pct
            strong_loss = _is_strong_baseline_loss(
                lead_time_model_win_count,
                lead_time_windows_evaluated,
            )
            if ratio <= threshold_ratio:
                margin_gain = max(0.0, threshold_ratio - ratio)
                confidence += min(0.12, 0.05 + (0.25 * margin_gain))
            else:
                shortfall = _baseline_margin_shortfall_wmape_pct(
                    lead_time_wmape_pct,
                    lead_time_baseline_wmape_pct,
                    tier,
                )
                tolerance = _baseline_margin_tolerance_wmape_pct(lead_time_baseline_wmape_pct, tier)
                if shortfall > tolerance:
                    margin_loss = ratio - threshold_ratio
                    if strong_loss:
                        confidence -= min(0.20, 0.10 + (0.30 * margin_loss))
                    else:
                        confidence -= min(0.07, 0.03 + (0.12 * margin_loss))
                else:
                    confidence -= min(0.05, 0.02 + (0.01 * max(shortfall, 0.0)))
                # Only SKUs with clear tier-adjusted baseline wins and multi-window support
                # can be high confidence.
                if strong_loss:
                    confidence = min(confidence, HIGH_CONFIDENCE_MIN - 0.01)

    win_ratio = _baseline_win_ratio(lead_time_model_win_count, lead_time_windows_evaluated)
    if win_ratio is not None:
        if win_ratio >= 0.75:
            confidence += 0.05
        elif win_ratio <= 0.25:
            confidence -= 0.08
        elif win_ratio < 0.5:
            confidence -= 0.03

    return float(max(0.05, min(0.99, confidence)))


def _recommendation_gate_reason(
    score: CandidateScore,
    quality: ForecastDataQuality,
    confidence: float,
    *,
    lead_time_wmape_pct: float | None = None,
    lead_time_baseline_wmape_pct: float | None = None,
    lead_time_model_win_count: int | None = None,
    lead_time_windows_evaluated: int | None = None,
    history_lag_days: int | None = None,
    days_since_last_sale: int | None = None,
) -> str | None:
    reasons: list[str] = []

    if quality.status != "ok":
        reasons.append(quality.status)
    if quality.history_days < MIN_ACTIONABLE_HISTORY_DAYS:
        reasons.append("history_lt_30d")
    if quality.non_zero_days < MIN_ACTIONABLE_NON_ZERO_DAYS:
        reasons.append("few_non_zero_days")
    if history_lag_days is not None and history_lag_days > MAX_HISTORY_LAG_DAYS:
        reasons.append("stale_history")
    if days_since_last_sale is not None and days_since_last_sale > MAX_DAYS_SINCE_LAST_SALE:
        reasons.append("no_recent_sales_30d")

    wmape = lead_time_wmape_pct if lead_time_wmape_pct is not None else score.wmape_pct
    if wmape is None:
        reasons.append("wmape_unavailable")
    elif wmape > MAX_ACTIONABLE_WMAPE_PCT:
        reasons.append("wmape_high")

    if (
        lead_time_wmape_pct is not None
        and lead_time_baseline_wmape_pct is not None
        and lead_time_baseline_wmape_pct > 0
    ):
        tier = _resolved_data_tier(quality)
        threshold_ratio = _margin_threshold_for_tier(tier)
        if (lead_time_wmape_pct / lead_time_baseline_wmape_pct) > threshold_ratio:
            shortfall = _baseline_margin_shortfall_wmape_pct(
                lead_time_wmape_pct,
                lead_time_baseline_wmape_pct,
                tier,
            )
            tolerance = _baseline_margin_tolerance_wmape_pct(lead_time_baseline_wmape_pct, tier)
            strong_loss = _is_strong_baseline_loss(
                lead_time_model_win_count,
                lead_time_windows_evaluated,
            )
            if shortfall > tolerance and strong_loss:
                reasons.append("baseline_not_beaten")

    if confidence < MIN_ACTIONABLE_CONFIDENCE:
        reasons.append("confidence_low")

    if not reasons:
        return None
    return ",".join(reasons)


def _parse_reason_tokens(reason: str | None) -> set[str]:
    if reason is None or not reason.strip():
        return set()
    return {token.strip() for token in reason.split(",") if token.strip()}


def _recommendation_action(reason_tokens: set[str]) -> str:
    if reason_tokens & HARD_GATE_REASONS:
        return "hard_gate"
    if _recommendation_fallback_reason(reason_tokens) is not None:
        return "baseline_fallback"
    return "none"


def _recommendation_fallback_reason(reason_tokens: set[str]) -> str | None:
    if CHAMPION_LOCK_FALLBACK_REASON in reason_tokens:
        return CHAMPION_LOCK_FALLBACK_REASON
    if BASELINE_FALLBACK_REASON in reason_tokens:
        return BASELINE_FALLBACK_REASON
    if WMAPE_FALLBACK_REASON in reason_tokens:
        return WMAPE_FALLBACK_REASON
    if STALE_HISTORY_FALLBACK_REASON in reason_tokens:
        return STALE_HISTORY_FALLBACK_REASON
    if NON_MATURE_GUARDRAIL_REASON in reason_tokens:
        return NON_MATURE_GUARDRAIL_REASON
    return None


def run_daily_forecast(
    db: Session | None = None,
    horizon_days: int = 30,
    *,
    qa_mode: str = "warn",
) -> int:
    own_session = db is None
    session = db or SessionLocal()
    reorder_service = ReorderService()
    resolved_qa_mode = _parse_qa_mode(qa_mode)

    try:
        run = ForecastRun(model_version="auto", horizon_days=horizon_days, notes=None)
        session.add(run)
        session.flush()

        model_versions: set[str] = set()
        model_usage: dict[str, int] = {}
        quality_warnings: list[str] = []
        gated_recommendations: list[str] = []
        fallback_recommendations: list[str] = []

        products = list(session.scalars(select(Product).where(Product.active.is_(True))).all())
        sales_histories: dict[int, pd.DataFrame] = {
            product.id: _load_sales_history(session, product.id) for product in products
        }
        stock_movements_map: dict[int, pd.DataFrame] = {
            product.id: _load_stock_movements(session, product.id) for product in products
        }
        analog_daily_priors = _build_analog_daily_priors(products, sales_histories)
        qa_payload = _evaluate_data_quality_precheck(products, sales_histories)
        qa_summary = qa_payload.get("summary", {}) if isinstance(qa_payload.get("summary"), dict) else {}
        qa_report_path = _write_data_quality_report(run.id, qa_payload)
        critical_skus = int(qa_summary.get("critical_skus", 0))
        warning_skus = int(qa_summary.get("warning_skus", 0))
        issue_type_count = int(qa_summary.get("issue_type_count", 0))

        if resolved_qa_mode == "strict" and critical_skus > 0:
            raise RuntimeError(
                "Data QA gate failed before forecasting: "
                f"critical_skus={critical_skus}, warning_skus={warning_skus}, "
                f"report={qa_report_path}"
            )

        for product in products:
            sales_history = sales_histories.get(product.id, pd.DataFrame(columns=["date", "units"]))
            stock_movements = stock_movements_map.get(
                product.id,
                pd.DataFrame(columns=["occurred_at", "qty_delta", "movement_type"]),
            )
            history_lag_days, days_since_last_sale = _sales_recency_days(sales_history)
            analog_daily_prior = analog_daily_priors.get(product.id)
            lead_time_days = _lead_time_days(session, product)
            forecast_result = forecast_product_daily_units_with_diagnostics(
                sales_history,
                horizon_days=horizon_days,
                lead_time_days=lead_time_days,
                stock_movements=stock_movements,
            )
            diagnostics = forecast_result.diagnostics
            forecast_frame = forecast_result.forecast_frame.copy()

            model_name = diagnostics.selected_model_name
            model_versions.add(model_name)
            model_usage[model_name] = model_usage.get(model_name, 0) + 1

            quality = diagnostics.quality
            analog_applied = _apply_analog_prior_fallback(
                forecast_frame,
                quality,
                analog_daily_prior,
            )
            if analog_applied:
                quality.notes.append(
                    f"Applied analog prior fallback at {analog_daily_prior:.2f} units/day for {quality.data_tier} tier."
                )
            if quality.status != "ok":
                quality_warnings.append(f"{product.sku}:{quality.status}")

            history_units = sales_history["units"].tolist() if not sales_history.empty else []
            safety_stock = product.safety_stock
            if safety_stock <= 0 and history_units:
                safety_stock = reorder_service.compute_safety_stock(history_units, lead_time_days)
            (
                lead_time_wmape,
                lead_time_baseline_wmape,
                lead_time_model_win_count,
                lead_time_windows_evaluated,
            ) = _lead_time_operational_backtest(
                sales_history,
                stock_movements,
                lead_time_days,
                analog_daily_prior=analog_daily_prior,
            )

            confidence = _calibrate_confidence(
                diagnostics.selected_score,
                quality,
                lead_time_wmape_pct=lead_time_wmape,
                lead_time_baseline_wmape_pct=lead_time_baseline_wmape,
                lead_time_model_win_count=lead_time_model_win_count,
                lead_time_windows_evaluated=lead_time_windows_evaluated,
                history_lag_days=history_lag_days,
                days_since_last_sale=days_since_last_sale,
            )
            reorder = reorder_service.compute_reorder(
                current_stock=_current_stock(session, product.id),
                forecast_frame=forecast_frame,
                lead_time_days=lead_time_days,
                reorder_min_qty=product.reorder_min_qty,
                reorder_multiple=product.reorder_multiple,
                safety_stock=safety_stock,
                recent_actual_daily_units=history_units,
                model_wmape_pct=lead_time_wmape if lead_time_wmape is not None else diagnostics.selected_score.wmape_pct,
                confidence_score=confidence,
            )

            predicted_stockout_date = reorder.predicted_stockout_date
            reorder_point = reorder.reorder_point
            suggested_qty = reorder.suggested_qty
            confidence_score = reorder.confidence_score
            persisted_forecast_frame = forecast_frame
            gate_reason = _recommendation_gate_reason(
                diagnostics.selected_score,
                quality,
                confidence_score,
                lead_time_wmape_pct=lead_time_wmape,
                lead_time_baseline_wmape_pct=lead_time_baseline_wmape,
                lead_time_model_win_count=lead_time_model_win_count,
                lead_time_windows_evaluated=lead_time_windows_evaluated,
                history_lag_days=history_lag_days,
                days_since_last_sale=days_since_last_sale,
            )
            reason_tokens = _parse_reason_tokens(gate_reason)
            action = _recommendation_action(reason_tokens)
            reason_tokens, action = _apply_champion_lock_guardrail(
                reason_tokens,
                action=action,
                lead_time_model_win_count=lead_time_model_win_count,
                lead_time_windows_evaluated=lead_time_windows_evaluated,
            )
            reason_tokens, action = _apply_non_mature_guardrail(
                reason_tokens,
                action=action,
                quality=quality,
                sales_history=sales_history,
                history_lag_days=history_lag_days,
            )
            gate_reason = ",".join(sorted(reason_tokens)) if reason_tokens else None
            if action == "hard_gate":
                predicted_stockout_date = None
                suggested_qty = 0
                confidence_score = min(confidence_score, 0.49)
                gated_recommendations.append(f"{product.sku}:{gate_reason or 'hard_gate'}")
            elif action == "baseline_fallback":
                baseline_frame = _baseline_forecast_frame(sales_history, forecast_frame)
                baseline_reorder = reorder_service.compute_reorder(
                    current_stock=_current_stock(session, product.id),
                    forecast_frame=baseline_frame,
                    lead_time_days=lead_time_days,
                    reorder_min_qty=product.reorder_min_qty,
                    reorder_multiple=product.reorder_multiple,
                    safety_stock=safety_stock,
                    recent_actual_daily_units=history_units,
                    model_wmape_pct=lead_time_baseline_wmape,
                    confidence_score=confidence_score,
                )
                persisted_forecast_frame = baseline_frame
                predicted_stockout_date = baseline_reorder.predicted_stockout_date
                reorder_point = baseline_reorder.reorder_point
                suggested_qty = baseline_reorder.suggested_qty
                confidence_score = min(
                    BASELINE_FALLBACK_CONFIDENCE_CEIL,
                    max(confidence_score, BASELINE_FALLBACK_CONFIDENCE_FLOOR),
                )
                fallback_reason = _recommendation_fallback_reason(reason_tokens) or BASELINE_FALLBACK_REASON
                fallback_recommendations.append(f"{product.sku}:{fallback_reason}")

            for _, row in persisted_forecast_frame.iterrows():
                session.add(
                    SkuForecast(
                        run_id=run.id,
                        product_id=product.id,
                        forecast_date=row["forecast_date"],
                        predicted_units=float(row["predicted_units"]),
                        lower_ci=float(row["lower_ci"]),
                        upper_ci=float(row["upper_ci"]),
                    )
                )

            session.add(
                ReorderRecommendation(
                    run_id=run.id,
                    product_id=product.id,
                    predicted_stockout_date=predicted_stockout_date,
                    reorder_point=reorder_point,
                    suggested_qty=suggested_qty,
                    confidence_score=confidence_score,
                )
            )

        if model_usage:
            run.model_version = ",".join(f"{name}:{count}" for name, count in sorted(model_usage.items()))
        else:
            run.model_version = ",".join(sorted(model_versions)) if model_versions else "NaiveMA"

        quality_note = ";".join(sorted(quality_warnings)[:30]) if quality_warnings else "none"
        gated_note = ";".join(sorted(gated_recommendations)[:30]) if gated_recommendations else "none"
        fallback_note = ";".join(sorted(fallback_recommendations)[:30]) if fallback_recommendations else "none"
        qa_note = f"critical:{critical_skus},warning:{warning_skus},issue_types:{issue_type_count}"
        run.notes = (
            f"qa={qa_note}|qa_report={qa_report_path.name}|"
            f"quality_flags={quality_note}|gated={gated_note}|fallback={fallback_note}"
        )

        session.commit()
        return run.id
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily demand forecast job.")
    parser.add_argument("--horizon-days", type=int, default=30)
    parser.add_argument(
        "--qa-mode",
        type=str,
        default="warn",
        choices=sorted(DATA_QA_MODES),
        help="Pre-forecast data-quality gate mode (off|warn|strict).",
    )
    args = parser.parse_args()

    run_id = run_daily_forecast(horizon_days=args.horizon_days, qa_mode=args.qa_mode)
    print(f"forecast_run_id={run_id}")
    with SessionLocal() as db:
        run = db.get(ForecastRun, run_id)
        notes = run.notes if run is not None else None
    if notes:
        for section in notes.split("|"):
            section = section.strip()
            if section.startswith("qa="):
                print(f"forecast_data_qa_summary={section.split('=', 1)[1]}")
            if section.startswith("qa_report="):
                print(f"forecast_data_qa_report={section.split('=', 1)[1]}")


if __name__ == "__main__":
    main()
