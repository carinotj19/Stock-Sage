from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from math import comb
from pathlib import Path
from random import Random
from statistics import mean
import json

import pandas as pd
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    CompetitorPriceSnapshot,
    CompetitorSource,
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
from app.jobs.run_forecast_daily import (
    _apply_champion_lock_guardrail,
    _baseline_forecast_frame,
    _calibrate_confidence,
    _lead_time_operational_backtest,
    _parse_reason_tokens,
    _recommendation_action,
    _recommendation_gate_reason,
)
from app.ml.predict import (
    MIN_HISTORY_DAYS,
    MIN_NON_ZERO_DAYS,
    MIN_NON_ZERO_RATIO,
    estimate_censored_sales_dates,
    filter_stock_movements_on_or_before,
    forecast_product_daily_units_with_diagnostics,
)
from app.schemas.dashboard import (
    DashboardKpis,
    ForecastEvaluationMetrics,
    ForecastRunComparisonDelta,
    ForecastRunComparisonMetrics,
    ForecastRunComparisonResponse,
    ForecastRunComparisonRun,
    ForecastRunComparisonSkuRow,
    ForecastRunValidationComparison,
    ForecastRunValidationDelta,
    ForecastRunValidationSkuRow,
    ForecastRunValidationSnapshot,
    ForecastRunComparisonWindow,
    ForecastExplainabilityRow,
    ForecastReportResponse,
    ForecastReportSummary,
    ItemDemandPoint,
    ItemForecastDetail,
    ItemPriceAnalysis,
    ItemPriceBenchmark,
    LowStockRow,
    ScraperSourceQualityRow,
    SalesTrendPoint,
    StockoutPredictionRow,
)

MATURE_MAX_HISTORY_LAG_DAYS = 14
MATURE_MIN_TRAILING_30_NON_ZERO_DAYS = 2


class DashboardService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_low_stock(self) -> list[LowStockRow]:
        statement = (
            select(Product, InventoryBalance.on_hand_qty)
            .outerjoin(InventoryBalance, InventoryBalance.product_id == Product.id)
            .where(Product.active.is_(True))
            .order_by(Product.name.asc())
        )
        rows = self.db.execute(statement).all()

        low_stock: list[LowStockRow] = []
        for product, on_hand_qty in rows:
            current_qty = on_hand_qty if on_hand_qty is not None else 0
            threshold = product.reorder_min_qty + product.safety_stock
            if current_qty <= threshold:
                low_stock.append(
                    LowStockRow(
                        product_id=product.id,
                        sku=product.sku,
                        name=product.name,
                        on_hand_qty=current_qty,
                        reorder_threshold=threshold,
                    )
                )

        low_stock.sort(key=lambda row: row.on_hand_qty - row.reorder_threshold)
        return low_stock

    def get_sales_trend(self, days: int) -> list[SalesTrendPoint]:
        safe_days = max(days, 1)
        start_date = date.today() - timedelta(days=safe_days - 1)

        statement = (
            select(
                func.date(SalesTransaction.sold_at).label("sale_date"),
                func.sum(SalesTransaction.total_amount).label("total_sales"),
                func.count(SalesTransaction.id).label("transactions"),
            )
            .where(func.date(SalesTransaction.sold_at) >= start_date)
            .group_by("sale_date")
            .order_by("sale_date")
        )
        rows = self.db.execute(statement).all()

        trend: list[SalesTrendPoint] = []
        for row in rows:
            sale_date = row.sale_date
            if isinstance(sale_date, str):
                parsed_date = date.fromisoformat(sale_date)
            else:
                parsed_date = sale_date

            trend.append(
                SalesTrendPoint(
                    date=parsed_date,
                    total_sales=Decimal(str(row.total_sales or 0)),
                    transactions=int(row.transactions or 0),
                )
            )

        return trend

    def get_kpis(self) -> DashboardKpis:
        sku_count = int(self.db.scalar(select(func.count()).select_from(Product).where(Product.active.is_(True))) or 0)

        low_stock_count = len(self.get_low_stock())

        now_utc = datetime.now(timezone.utc)
        day_start_utc = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
        day_end_utc = day_start_utc + timedelta(days=1)
        today_sales_raw = self.db.scalar(
            select(func.sum(SalesTransaction.total_amount))
            .where(SalesTransaction.sold_at >= day_start_utc)
            .where(SalesTransaction.sold_at < day_end_utc)
        )
        today_sales = Decimal(str(today_sales_raw or 0))

        return DashboardKpis(sku_count=sku_count, low_stock_count=low_stock_count, today_sales=today_sales)

    @staticmethod
    def _source_mode(scrape_config_json: str | None) -> str:
        if not scrape_config_json:
            return "standard"
        try:
            payload = json.loads(scrape_config_json)
        except json.JSONDecodeError:
            return "invalid_config"
        mode = payload.get("mode")
        if not isinstance(mode, str) or not mode.strip():
            return "standard"
        return mode.strip().lower()

    @staticmethod
    def _source_runtime_state(scrape_config_json: str | None) -> dict[str, object]:
        if not scrape_config_json:
            return {}
        try:
            payload = json.loads(scrape_config_json)
        except json.JSONDecodeError:
            return {}
        runtime = payload.get("runtime_state")
        if not isinstance(runtime, dict):
            return {}
        return runtime

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def get_scraper_source_quality(self, window_hours: int = 24) -> list[ScraperSourceQualityRow]:
        safe_window = max(1, min(168, int(window_hours)))
        now_utc = datetime.now(timezone.utc)
        window_start = now_utc - timedelta(hours=safe_window)

        active_sku_count = int(
            self.db.scalar(select(func.count()).select_from(Product).where(Product.active.is_(True)))
            or 0
        )

        snapshots_in_window = case(
            (CompetitorPriceSnapshot.scraped_at >= window_start, CompetitorPriceSnapshot.id),
            else_=None,
        )
        matched_products_in_window = case(
            (CompetitorPriceSnapshot.scraped_at >= window_start, CompetitorPriceSnapshot.product_id),
            else_=None,
        )

        statement = (
            select(
                CompetitorSource.id,
                CompetitorSource.name,
                CompetitorSource.enabled,
                CompetitorSource.last_run_at,
                CompetitorSource.scrape_config_json,
                func.max(CompetitorPriceSnapshot.scraped_at).label("latest_scraped_at"),
                func.count(snapshots_in_window).label("snapshots_24h"),
                func.count(func.distinct(matched_products_in_window)).label("matched_skus_24h"),
            )
            .outerjoin(CompetitorPriceSnapshot, CompetitorPriceSnapshot.source_id == CompetitorSource.id)
            .group_by(
                CompetitorSource.id,
                CompetitorSource.name,
                CompetitorSource.enabled,
                CompetitorSource.last_run_at,
                CompetitorSource.scrape_config_json,
            )
            .order_by(CompetitorSource.name.asc())
        )

        rows = self.db.execute(statement).all()
        quality_rows: list[ScraperSourceQualityRow] = []

        for row in rows:
            matched_skus_24h = int(row.matched_skus_24h or 0)
            snapshots_24h = int(row.snapshots_24h or 0)
            latest_scraped_at = self._as_utc(row.latest_scraped_at)
            last_run_at = self._as_utc(row.last_run_at)
            latest_activity_at = latest_scraped_at
            if latest_activity_at is None or (last_run_at is not None and last_run_at > latest_activity_at):
                latest_activity_at = last_run_at
            minutes_since_latest = (
                int((now_utc - latest_activity_at).total_seconds() // 60)
                if latest_activity_at is not None
                else None
            )
            coverage_pct = (
                round((matched_skus_24h / active_sku_count) * 100.0, 1)
                if active_sku_count > 0
                else 0.0
            )
            stale = minutes_since_latest is None or minutes_since_latest > (safe_window * 60)
            runtime_state = self._source_runtime_state(row.scrape_config_json)
            consecutive_zero_runs = self._safe_int(runtime_state.get("consecutive_zero_insert_runs"), 0)
            last_run_inserted = self._safe_int(runtime_state.get("last_run_inserted"), snapshots_24h)
            last_run_attempted = self._safe_int(runtime_state.get("last_run_attempted_products"), 0)
            configured_reason = runtime_state.get("degraded_reason")
            degraded_reason = str(configured_reason).strip() if isinstance(configured_reason, str) else ""
            degraded = (
                not stale
                and last_run_inserted == 0
                and consecutive_zero_runs >= 2
                and (last_run_attempted > 0 or bool(degraded_reason))
            )
            if degraded and not degraded_reason:
                degraded_reason = "repeated_zero_insert_runs"
            effective_coverage = (
                round(min(coverage_pct, 25.0), 1)
                if degraded
                else coverage_pct
            )

            quality_rows.append(
                ScraperSourceQualityRow(
                    source_id=int(row.id),
                    source_name=str(row.name),
                    mode=self._source_mode(row.scrape_config_json),
                    enabled=bool(row.enabled),
                    snapshots_24h=snapshots_24h,
                    matched_skus_24h=matched_skus_24h,
                    coverage_pct_24h=coverage_pct,
                    effective_coverage_pct_24h=effective_coverage,
                    latest_scraped_at=latest_activity_at,
                    minutes_since_latest=minutes_since_latest,
                    stale=stale,
                    degraded=degraded,
                    degradation_reason=degraded_reason or None,
                )
            )

        quality_rows.sort(
            key=lambda item: (
                item.effective_coverage_pct_24h if item.effective_coverage_pct_24h is not None else item.coverage_pct_24h,
                item.matched_skus_24h,
                item.snapshots_24h,
            ),
            reverse=True,
        )
        return quality_rows

    def get_stockout_predictions(self) -> list[StockoutPredictionRow]:
        latest_run_id = self.db.scalar(select(func.max(ReorderRecommendation.run_id)))
        if latest_run_id is None:
            return []

        statement = (
            select(
                ReorderRecommendation.product_id,
                Product.sku,
                Product.name,
                ReorderRecommendation.predicted_stockout_date,
                ReorderRecommendation.suggested_qty,
            )
            .join(Product, Product.id == ReorderRecommendation.product_id)
            .where(ReorderRecommendation.run_id == latest_run_id)
            .order_by(
                ReorderRecommendation.predicted_stockout_date.is_(None).asc(),
                ReorderRecommendation.predicted_stockout_date.asc(),
                Product.sku.asc(),
            )
        )
        rows = self.db.execute(statement).all()
        return [
            StockoutPredictionRow(
                product_id=row.product_id,
                sku=row.sku,
                name=row.name,
                predicted_stockout_date=row.predicted_stockout_date,
                suggested_qty=row.suggested_qty,
            )
            for row in rows
        ]

    def _load_sales_history_dense(self, product_id: int) -> pd.DataFrame:
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
        rows = self.db.execute(statement).all()
        if not rows:
            return pd.DataFrame(columns=["date", "units"])

        raw = pd.DataFrame(
            [
                {
                    "date": row.sale_date if isinstance(row.sale_date, date) else date.fromisoformat(str(row.sale_date)),
                    "units": float(row.units or 0),
                }
                for row in rows
            ],
            columns=["date", "units"],
        )
        end_date = max(raw["date"].max(), datetime.now(timezone.utc).date())
        full_dates = pd.date_range(start=raw["date"].min(), end=end_date, freq="D").date
        dense = pd.DataFrame({"date": full_dates})
        dense = dense.merge(raw, on="date", how="left")
        dense["units"] = dense["units"].fillna(0.0)
        return dense

    def _load_stock_movements(self, product_id: int) -> pd.DataFrame:
        statement = (
            select(
                StockMovement.occurred_at.label("occurred_at"),
                StockMovement.qty_delta.label("qty_delta"),
                StockMovement.movement_type.label("movement_type"),
            )
            .where(StockMovement.product_id == product_id)
            .order_by(StockMovement.occurred_at.asc())
        )
        rows = self.db.execute(statement).all()
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

    def _lead_time_days_for_product(self, product_id: int) -> int:
        statement = (
            select(Supplier.lead_time_days_default)
            .select_from(Product)
            .outerjoin(Supplier, Supplier.id == Product.supplier_id)
            .where(Product.id == product_id)
        )
        value = self.db.scalar(statement)
        return max(1, int(value or 7))

    @staticmethod
    def _error_metrics(actual: list[float], predicted: list[float]) -> tuple[float, float | None]:
        if not actual:
            return 0.0, None

        abs_errors = [abs(a - p) for a, p in zip(actual, predicted)]
        mae = mean(abs_errors)

        non_zero_actual = [(a, p) for a, p in zip(actual, predicted) if a > 0]
        if not non_zero_actual:
            return mae, None

        ape = [abs(a - p) / a for a, p in non_zero_actual]
        return mae, mean(ape) * 100

    @staticmethod
    def _weighted_mape_pct(actual: list[float], predicted: list[float]) -> float | None:
        if not actual:
            return None
        denominator = sum(abs(value) for value in actual)
        if denominator <= 0:
            return None
        numerator = sum(abs(a - p) for a, p in zip(actual, predicted))
        return (numerator / denominator) * 100

    @staticmethod
    def _bootstrap_ci95(values: list[float], *, seed: int = 42, iterations: int = 2000) -> tuple[float | None, float | None]:
        if not values:
            return (None, None)
        if len(values) == 1:
            only = float(values[0])
            return (only, only)

        rng = Random(seed)
        n = len(values)
        means: list[float] = []
        for _ in range(iterations):
            sample = [values[rng.randrange(n)] for _ in range(n)]
            means.append(float(mean(sample)))
        means.sort()
        low_idx = int(0.025 * (iterations - 1))
        high_idx = int(0.975 * (iterations - 1))
        return (means[low_idx], means[high_idx])

    @staticmethod
    def _binomial_two_sided_p_value(wins: int, losses: int) -> float | None:
        n = wins + losses
        if n == 0:
            return None
        k = min(wins, losses)
        prob_le_k = sum(comb(n, i) for i in range(0, k + 1)) * (0.5 ** n)
        p_value = min(1.0, 2.0 * prob_le_k)
        return float(p_value)

    @staticmethod
    def _average_or_none(values: list[float]) -> float | None:
        if not values:
            return None
        return float(mean(values))

    @staticmethod
    def _float_delta(candidate: float | None, baseline: float | None) -> float | None:
        if candidate is None or baseline is None:
            return None
        return float(candidate - baseline)

    @staticmethod
    def _improvement_pct(candidate: float | None, baseline: float | None) -> float | None:
        if candidate is None or baseline is None:
            return None
        denominator = abs(float(baseline))
        if denominator <= 0:
            return None
        return ((float(baseline) - float(candidate)) / denominator) * 100.0

    @staticmethod
    def _mature_history_thresholds() -> tuple[int, int, float, int, int]:
        return (
            max(MIN_HISTORY_DAYS * 2, 42),
            max(MIN_NON_ZERO_DAYS * 2, 12),
            max(MIN_NON_ZERO_RATIO * 2.0, 0.18),
            MATURE_MAX_HISTORY_LAG_DAYS,
            MATURE_MIN_TRAILING_30_NON_ZERO_DAYS,
        )

    @classmethod
    def _mature_sku_criteria_text(cls) -> str:
        (
            min_history_days,
            min_non_zero_days,
            min_non_zero_ratio,
            max_history_lag_days,
            min_trailing_30_non_zero_days,
        ) = cls._mature_history_thresholds()
        return (
            f"history_days>={min_history_days}, "
            f"non_zero_days>={min_non_zero_days}, "
            f"non_zero_ratio>={min_non_zero_ratio * 100:.1f}%, "
            f"history_lag_days<={max_history_lag_days}, "
            f"trailing_30_non_zero_days>={min_trailing_30_non_zero_days}"
        )

    @classmethod
    def _is_mature_history(
        cls,
        history: pd.DataFrame,
        *,
        censored_dates: set[pd.Timestamp] | None = None,
    ) -> bool:
        if history.empty:
            return False

        (
            min_history_days,
            min_non_zero_days,
            min_non_zero_ratio,
            max_history_lag_days,
            min_trailing_30_non_zero_days,
        ) = cls._mature_history_thresholds()
        working_history = history.copy()
        if censored_dates:
            censored_date_values = {pd.Timestamp(value).date() for value in censored_dates}
            history_dates = pd.to_datetime(working_history["date"]).dt.date
            working_history = working_history.loc[~history_dates.isin(censored_date_values)].copy()
            if working_history.empty:
                return False

        working_history["date"] = pd.to_datetime(working_history["date"]).dt.normalize()
        working_history = working_history.sort_values("date").reset_index(drop=True)
        units = working_history["units"].astype(float)
        history_days = len(units)
        non_zero_days = int((units > 0.0).sum())
        non_zero_ratio = float(non_zero_days / history_days) if history_days > 0 else 0.0
        trailing_30_non_zero_days = int((units.tail(30) > 0.0).sum()) if history_days > 0 else 0
        last_history_ts = working_history["date"].max() if history_days > 0 else None
        history_lag_days = (
            int((pd.Timestamp.utcnow().date() - pd.Timestamp(last_history_ts).date()).days)
            if last_history_ts is not None
            else None
        )

        return (
            history_days >= min_history_days
            and non_zero_days >= min_non_zero_days
            and non_zero_ratio >= min_non_zero_ratio
            and history_lag_days is not None
            and history_lag_days <= max_history_lag_days
            and trailing_30_non_zero_days >= min_trailing_30_non_zero_days
        )

    def _evaluate_forecast_quality(self, product_ids: list[int], evaluation_days: int) -> ForecastEvaluationMetrics:
        safe_days = max(3, min(30, evaluation_days))
        model_mae_values: list[float] = []
        model_mape_values: list[float] = []
        model_wmape_values: list[float] = []
        baseline_mae_values: list[float] = []
        baseline_mape_values: list[float] = []
        baseline_wmape_values: list[float] = []
        mae_improvement_values: list[float] = []
        wmape_improvement_values: list[float] = []
        mae_diff_values: list[float] = []
        wmape_diff_values: list[float] = []
        better_than_baseline_skus = 0
        compared_skus = 0

        for product_id in product_ids:
            history = self._load_sales_history_dense(product_id)
            stock_movements = self._load_stock_movements(product_id)
            lead_time_days = self._lead_time_days_for_product(product_id)
            if history.empty or len(history) < safe_days + 7:
                continue

            train = history.iloc[:-safe_days].copy()
            holdout = history.iloc[-safe_days:].copy()
            if train.empty or holdout.empty:
                continue

            result = forecast_product_daily_units_with_diagnostics(
                train[["date", "units"]],
                horizon_days=safe_days,
                lead_time_days=lead_time_days,
                stock_movements=stock_movements,
            )
            train_stock_movements = stock_movements
            if not stock_movements.empty and "occurred_at" in stock_movements.columns:
                train_stock_movements = filter_stock_movements_on_or_before(stock_movements, train["date"])

            (
                lead_time_wmape,
                lead_time_baseline_wmape,
                lead_time_model_win_count,
                lead_time_windows_evaluated,
            ) = _lead_time_operational_backtest(
                train[["date", "units"]],
                train_stock_movements,
                lead_time_days,
            )
            quality = result.diagnostics.quality
            confidence = _calibrate_confidence(
                result.diagnostics.selected_score,
                quality,
                lead_time_wmape_pct=lead_time_wmape,
                lead_time_baseline_wmape_pct=lead_time_baseline_wmape,
                lead_time_model_win_count=lead_time_model_win_count,
                lead_time_windows_evaluated=lead_time_windows_evaluated,
            )
            gate_reason = _recommendation_gate_reason(
                result.diagnostics.selected_score,
                quality,
                confidence,
                lead_time_wmape_pct=lead_time_wmape,
                lead_time_baseline_wmape_pct=lead_time_baseline_wmape,
                lead_time_model_win_count=lead_time_model_win_count,
                lead_time_windows_evaluated=lead_time_windows_evaluated,
            )
            reason_tokens = _parse_reason_tokens(gate_reason)
            action = _recommendation_action(reason_tokens)
            reason_tokens, action = _apply_champion_lock_guardrail(
                reason_tokens,
                action=action,
                lead_time_model_win_count=lead_time_model_win_count,
                lead_time_windows_evaluated=lead_time_windows_evaluated,
            )

            forecast_frame = result.forecast_frame
            if action == "baseline_fallback":
                forecast_frame = _baseline_forecast_frame(train[["date", "units"]], result.forecast_frame)

            predicted = forecast_frame["predicted_units"].astype(float).tolist()
            actual = holdout["units"].astype(float).tolist()
            horizon = min(len(actual), len(predicted))
            if horizon == 0:
                continue

            actual = actual[:horizon]
            predicted = predicted[:horizon]
            holdout_dates = pd.to_datetime(holdout["date"].iloc[:horizon]).dt.normalize()
            censored_dates = estimate_censored_sales_dates(
                history[["date", "units"]],
                stock_movements=stock_movements,
            )
            if censored_dates:
                active_mask = [date_value not in censored_dates for date_value in holdout_dates]
                actual = [value for value, keep in zip(actual, active_mask) if keep]
                predicted = [value for value, keep in zip(predicted, active_mask) if keep]
                horizon = min(len(actual), len(predicted))
                if horizon == 0:
                    continue
                actual = actual[:horizon]
                predicted = predicted[:horizon]

            model_mae, model_mape = self._error_metrics(actual, predicted)
            model_wmape = self._weighted_mape_pct(actual, predicted)

            trailing_window = train["units"].tail(min(7, len(train)))
            baseline_level = float(trailing_window.mean()) if not trailing_window.empty else 0.0
            baseline_pred = [baseline_level] * horizon
            baseline_mae, baseline_mape = self._error_metrics(actual, baseline_pred)
            baseline_wmape = self._weighted_mape_pct(actual, baseline_pred)

            model_mae_values.append(model_mae)
            baseline_mae_values.append(baseline_mae)
            if model_mape is not None:
                model_mape_values.append(model_mape)
            if baseline_mape is not None:
                baseline_mape_values.append(baseline_mape)
            if model_wmape is not None:
                model_wmape_values.append(model_wmape)
            if baseline_wmape is not None:
                baseline_wmape_values.append(baseline_wmape)

            if baseline_mae > 0:
                mae_improvement_values.append(((baseline_mae - model_mae) / baseline_mae) * 100.0)
                mae_diff_values.append(baseline_mae - model_mae)
                compared_skus += 1
                if model_mae < baseline_mae:
                    better_than_baseline_skus += 1

            if baseline_wmape is not None and baseline_wmape > 0 and model_wmape is not None:
                wmape_improvement_values.append(((baseline_wmape - model_wmape) / baseline_wmape) * 100.0)
                wmape_diff_values.append(baseline_wmape - model_wmape)

        mae_ci_low, mae_ci_high = self._bootstrap_ci95(mae_diff_values)
        wmape_ci_low, wmape_ci_high = self._bootstrap_ci95(wmape_diff_values)
        sign_test_p_value = self._binomial_two_sided_p_value(
            wins=better_than_baseline_skus,
            losses=max(compared_skus - better_than_baseline_skus, 0),
        )

        return ForecastEvaluationMetrics(
            evaluation_days=safe_days,
            evaluated_skus=len(model_mae_values),
            model_mae=self._average_or_none(model_mae_values),
            model_mape_pct=self._average_or_none(model_mape_values),
            model_wmape_pct=self._average_or_none(model_wmape_values),
            baseline_mae=self._average_or_none(baseline_mae_values),
            baseline_mape_pct=self._average_or_none(baseline_mape_values),
            baseline_wmape_pct=self._average_or_none(baseline_wmape_values),
            mae_improvement_pct=self._average_or_none(mae_improvement_values),
            wmape_improvement_pct=self._average_or_none(wmape_improvement_values),
            mae_diff_ci95_low=mae_ci_low,
            mae_diff_ci95_high=mae_ci_high,
            wmape_diff_ci95_low=wmape_ci_low,
            wmape_diff_ci95_high=wmape_ci_high,
            sign_test_p_value=sign_test_p_value,
            better_than_baseline_skus=better_than_baseline_skus,
            compared_skus=compared_skus,
        )

    @staticmethod
    def _build_reorder_explanation(row: ForecastExplainabilityRow) -> str:
        stockout_label = row.predicted_stockout_date.isoformat() if row.predicted_stockout_date else "not within horizon"
        if row.suggested_qty > 0:
            return (
                f"Lead-time demand and safety stock set reorder point at {row.reorder_point}. "
                f"Current stock is {row.on_hand_qty}, projected stockout is {stockout_label}, "
                f"so reorder recommendation is {row.suggested_qty} units."
            )
        return (
            f"Current stock ({row.on_hand_qty}) is sufficient against reorder point ({row.reorder_point}). "
            f"Projected stockout is {stockout_label}, so no reorder is suggested now."
        )

    @staticmethod
    def _parse_run_note_map(notes: str | None, key: str) -> dict[str, str]:
        if not notes:
            return {}

        sections = [section.strip() for section in notes.split("|") if section.strip()]
        key_prefix = f"{key}="
        payload = ""
        for section in sections:
            if section.startswith(key_prefix):
                payload = section[len(key_prefix):].strip()
                break
        if not payload or payload == "none":
            return {}

        mapping: dict[str, str] = {}
        for item in payload.split(";"):
            token = item.strip()
            if not token:
                continue
            if ":" not in token:
                mapping[token] = ""
                continue
            sku, reason = token.split(":", 1)
            mapping[sku.strip()] = reason.strip()
        return mapping

    @staticmethod
    def _parse_run_note_value(notes: str | None, key: str) -> str | None:
        if not notes:
            return None
        sections = [section.strip() for section in notes.split("|") if section.strip()]
        key_prefix = f"{key}="
        for section in sections:
            if section.startswith(key_prefix):
                value = section[len(key_prefix):].strip()
                if not value or value == "none":
                    return None
                return value
        return None

    @staticmethod
    def _format_optional_metric(value: float | None, decimals: int = 2, suffix: str = "") -> str:
        if value is None:
            return "n/a"
        return f"{value:.{decimals}f}{suffix}"

    def _render_markdown_report(
        self,
        run: ForecastRun,
        summary: ForecastReportSummary,
        evaluation_full: ForecastEvaluationMetrics,
        evaluation_mature: ForecastEvaluationMetrics,
        evaluation_non_mature: ForecastEvaluationMetrics | None,
        mature_sku_criteria: str,
        qa_summary: str | None,
        qa_report: str | None,
        rows: list[ForecastExplainabilityRow],
    ) -> str:
        report_lines = [
            "# Forecast Metrics Report",
            "",
            f"- Generated at: {datetime.utcnow().isoformat()}Z",
            f"- Forecast run ID: {run.id}",
            f"- Run timestamp: {run.run_at.isoformat()}",
            f"- Horizon days: {run.horizon_days}",
            f"- Model version(s): {run.model_version or 'n/a'}",
            f"- Data QA summary: {qa_summary or 'n/a'}",
            f"- Data QA report: {qa_report or 'n/a'}",
            "",
            "## Summary",
            f"- Forecasted SKUs: {summary.sku_count}",
            f"- Recommendations generated: {summary.recommendations_count}",
            f"- SKUs with stockout risk in horizon: {summary.stockout_within_horizon_count}",
            f"- SKUs needing reorder now: {summary.reorder_required_count}",
            f"- Total suggested reorder quantity: {summary.total_suggested_reorder_qty}",
            f"- Avg confidence: {self._format_optional_metric(summary.avg_confidence, 3)}",
            f"- Mature SKUs: {summary.mature_sku_count if summary.mature_sku_count is not None else 'n/a'}",
            f"- Non-mature SKUs: {summary.non_mature_sku_count if summary.non_mature_sku_count is not None else 'n/a'}",
            (
                f"- High-confidence SKUs (>=0.70): "
                f"{summary.high_confidence_count if summary.high_confidence_count is not None else 'n/a'}"
                f" | mature={summary.high_confidence_mature_count if summary.high_confidence_mature_count is not None else 'n/a'}"
                f" | non_mature={summary.high_confidence_non_mature_count if summary.high_confidence_non_mature_count is not None else 'n/a'}"
            ),
            "",
            "## Holdout Evaluation (Full Catalog)",
            f"- Evaluation window: {evaluation_full.evaluation_days} days",
            f"- Evaluated SKUs: {evaluation_full.evaluated_skus}",
            f"- Model MAE: {self._format_optional_metric(evaluation_full.model_mae, 3)}",
            f"- Model MAPE: {self._format_optional_metric(evaluation_full.model_mape_pct, 2, '%')}",
            f"- Model wMAPE: {self._format_optional_metric(evaluation_full.model_wmape_pct, 2, '%')}",
            f"- Baseline MAE: {self._format_optional_metric(evaluation_full.baseline_mae, 3)}",
            f"- Baseline MAPE: {self._format_optional_metric(evaluation_full.baseline_mape_pct, 2, '%')}",
            f"- Baseline wMAPE: {self._format_optional_metric(evaluation_full.baseline_wmape_pct, 2, '%')}",
            f"- MAE improvement vs baseline: {self._format_optional_metric(evaluation_full.mae_improvement_pct, 2, '%')}",
            f"- wMAPE improvement vs baseline: {self._format_optional_metric(evaluation_full.wmape_improvement_pct, 2, '%')}",
            (
                f"- MAE diff 95% CI (baseline-model): "
                f"[{self._format_optional_metric(evaluation_full.mae_diff_ci95_low, 3)}, "
                f"{self._format_optional_metric(evaluation_full.mae_diff_ci95_high, 3)}]"
            ),
            (
                f"- wMAPE diff 95% CI (baseline-model): "
                f"[{self._format_optional_metric(evaluation_full.wmape_diff_ci95_low, 2, '%')}, "
                f"{self._format_optional_metric(evaluation_full.wmape_diff_ci95_high, 2, '%')}]"
            ),
            (
                f"- Sign test p-value (MAE better-than-baseline): "
                f"{self._format_optional_metric(evaluation_full.sign_test_p_value, 4)} "
                f"({evaluation_full.better_than_baseline_skus}/{evaluation_full.compared_skus} SKUs improved)"
            ),
            "",
            "## Holdout Evaluation (Mature SKUs)",
            f"- Mature SKU criteria: {mature_sku_criteria}",
            f"- Evaluation window: {evaluation_mature.evaluation_days} days",
            f"- Evaluated SKUs: {evaluation_mature.evaluated_skus}",
            f"- Model MAE: {self._format_optional_metric(evaluation_mature.model_mae, 3)}",
            f"- Model MAPE: {self._format_optional_metric(evaluation_mature.model_mape_pct, 2, '%')}",
            f"- Model wMAPE: {self._format_optional_metric(evaluation_mature.model_wmape_pct, 2, '%')}",
            f"- Baseline MAE: {self._format_optional_metric(evaluation_mature.baseline_mae, 3)}",
            f"- Baseline MAPE: {self._format_optional_metric(evaluation_mature.baseline_mape_pct, 2, '%')}",
            f"- Baseline wMAPE: {self._format_optional_metric(evaluation_mature.baseline_wmape_pct, 2, '%')}",
            f"- MAE improvement vs baseline: {self._format_optional_metric(evaluation_mature.mae_improvement_pct, 2, '%')}",
            f"- wMAPE improvement vs baseline: {self._format_optional_metric(evaluation_mature.wmape_improvement_pct, 2, '%')}",
            (
                f"- MAE diff 95% CI (baseline-model): "
                f"[{self._format_optional_metric(evaluation_mature.mae_diff_ci95_low, 3)}, "
                f"{self._format_optional_metric(evaluation_mature.mae_diff_ci95_high, 3)}]"
            ),
            (
                f"- wMAPE diff 95% CI (baseline-model): "
                f"[{self._format_optional_metric(evaluation_mature.wmape_diff_ci95_low, 2, '%')}, "
                f"{self._format_optional_metric(evaluation_mature.wmape_diff_ci95_high, 2, '%')}]"
            ),
            (
                f"- Sign test p-value (MAE better-than-baseline): "
                f"{self._format_optional_metric(evaluation_mature.sign_test_p_value, 4)} "
                f"({evaluation_mature.better_than_baseline_skus}/{evaluation_mature.compared_skus} SKUs improved)"
            ),
            "",
            "## Holdout Evaluation (Non-Mature SKUs)",
        ]
        non_mature_metrics = evaluation_non_mature or ForecastEvaluationMetrics(
            evaluation_days=evaluation_full.evaluation_days,
            evaluated_skus=0,
            model_mae=None,
            model_mape_pct=None,
            model_wmape_pct=None,
            baseline_mae=None,
            baseline_mape_pct=None,
            baseline_wmape_pct=None,
        )
        report_lines.extend(
            [
                f"- Evaluation window: {non_mature_metrics.evaluation_days} days",
                f"- Evaluated SKUs: {non_mature_metrics.evaluated_skus}",
                f"- Model MAE: {self._format_optional_metric(non_mature_metrics.model_mae, 3)}",
                f"- Model MAPE: {self._format_optional_metric(non_mature_metrics.model_mape_pct, 2, '%')}",
                f"- Model wMAPE: {self._format_optional_metric(non_mature_metrics.model_wmape_pct, 2, '%')}",
                f"- Baseline MAE: {self._format_optional_metric(non_mature_metrics.baseline_mae, 3)}",
                f"- Baseline MAPE: {self._format_optional_metric(non_mature_metrics.baseline_mape_pct, 2, '%')}",
                f"- Baseline wMAPE: {self._format_optional_metric(non_mature_metrics.baseline_wmape_pct, 2, '%')}",
                (
                    f"- MAE improvement vs baseline: "
                    f"{self._format_optional_metric(non_mature_metrics.mae_improvement_pct, 2, '%')}"
                ),
                (
                    f"- wMAPE improvement vs baseline: "
                    f"{self._format_optional_metric(non_mature_metrics.wmape_improvement_pct, 2, '%')}"
                ),
                "",
            ]
        )
        report_lines.extend(
            [
            "## Top Reorder/Stockout Signals",
            ]
        )

        if not rows:
            report_lines.append("- No explainability rows available for this run.")
            return "\n".join(report_lines)

        ranked_rows = sorted(
            rows,
            key=lambda item: (
                item.predicted_stockout_date is None,
                item.predicted_stockout_date or date.max,
                -item.suggested_qty,
            ),
        )
        for row in ranked_rows[:10]:
            stockout_label = row.predicted_stockout_date.isoformat() if row.predicted_stockout_date else "none"
            report_lines.append(
                (
                    f"- {row.sku} | stockout={stockout_label} | reorder_point={row.reorder_point} "
                    f"| suggested_qty={row.suggested_qty} | confidence={self._format_optional_metric(row.confidence_score, 3)}"
                )
            )

        return "\n".join(report_lines)

    def _resolve_forecast_run_pair(
        self,
        *,
        baseline_run_id: int | None,
        candidate_run_id: int | None,
    ) -> tuple[ForecastRun, ForecastRun]:
        ordered_runs = list(self.db.scalars(select(ForecastRun).order_by(ForecastRun.id.desc())).all())
        if len(ordered_runs) < 2 and (baseline_run_id is None or candidate_run_id is None):
            raise ValueError("At least two forecast runs are required for comparison.")

        run_by_id = {run.id: run for run in ordered_runs}

        candidate_run = run_by_id.get(candidate_run_id) if candidate_run_id is not None else None
        if candidate_run is None:
            candidate_run = ordered_runs[0] if ordered_runs else None

        if candidate_run is None:
            raise ValueError("No forecast run found for comparison.")

        baseline_run = run_by_id.get(baseline_run_id) if baseline_run_id is not None else None
        if baseline_run is None:
            baseline_run = next((run for run in ordered_runs if run.id != candidate_run.id), None)

        if baseline_run is None:
            raise ValueError("Could not resolve a baseline forecast run for comparison.")
        if baseline_run.id == candidate_run.id:
            raise ValueError("baseline_run_id and candidate_run_id must refer to different runs.")

        if baseline_run.run_at > candidate_run.run_at:
            baseline_run, candidate_run = candidate_run, baseline_run

        return baseline_run, candidate_run

    def _load_run_forecast_values(
        self,
        run_id: int,
    ) -> tuple[dict[int, dict[str, object]], dict[int, dict[date, float]], dict[int, float]]:
        statement = (
            select(
                SkuForecast.product_id,
                Product.sku,
                Product.name,
                SkuForecast.forecast_date,
                SkuForecast.predicted_units,
            )
            .join(Product, Product.id == SkuForecast.product_id)
            .where(SkuForecast.run_id == run_id)
            .order_by(SkuForecast.product_id.asc(), SkuForecast.forecast_date.asc())
        )
        rows = self.db.execute(statement).all()

        product_meta: dict[int, dict[str, object]] = {}
        forecast_by_product: dict[int, dict[date, float]] = {}
        totals_by_product: dict[int, float] = {}
        for row in rows:
            product_meta[row.product_id] = {
                "sku": row.sku,
                "name": row.name,
            }
            product_forecasts = forecast_by_product.setdefault(row.product_id, {})
            product_forecasts[row.forecast_date] = float(row.predicted_units or 0.0)
            totals_by_product[row.product_id] = totals_by_product.get(row.product_id, 0.0) + float(row.predicted_units or 0.0)

        return product_meta, forecast_by_product, totals_by_product

    def _load_run_recommendations(self, run_id: int) -> dict[int, ReorderRecommendation]:
        rows = self.db.scalars(select(ReorderRecommendation).where(ReorderRecommendation.run_id == run_id)).all()
        return {row.product_id: row for row in rows}

    def _load_actual_units_lookup(
        self,
        *,
        product_ids: list[int],
        start_date: date,
        end_date: date,
    ) -> dict[tuple[int, date], float]:
        if not product_ids or start_date > end_date:
            return {}

        statement = (
            select(
                SalesItem.product_id,
                func.date(SalesTransaction.sold_at).label("sale_date"),
                func.sum(SalesItem.qty).label("units"),
            )
            .join(SalesTransaction, SalesItem.sales_transaction_id == SalesTransaction.id)
            .where(SalesItem.product_id.in_(product_ids))
            .where(func.date(SalesTransaction.sold_at) >= start_date)
            .where(func.date(SalesTransaction.sold_at) <= end_date)
            .group_by(SalesItem.product_id, "sale_date")
        )
        rows = self.db.execute(statement).all()

        actuals: dict[tuple[int, date], float] = {}
        for row in rows:
            sale_date = row.sale_date if isinstance(row.sale_date, date) else date.fromisoformat(str(row.sale_date))
            actuals[(int(row.product_id), sale_date)] = float(row.units or 0.0)
        return actuals

    def _build_run_comparison_metrics(
        self,
        *,
        actual: list[float],
        predicted: list[float],
        recommendations: dict[int, ReorderRecommendation],
        product_ids: list[int],
    ) -> ForecastRunComparisonMetrics:
        if actual:
            mae, mape_pct = self._error_metrics(actual, predicted)
            wmape_pct = self._weighted_mape_pct(actual, predicted)
        else:
            mae = None
            mape_pct = None
            wmape_pct = None

        confidences = [
            float(recommendations[product_id].confidence_score)
            for product_id in product_ids
            if product_id in recommendations and recommendations[product_id].confidence_score is not None
        ]
        rows = [recommendations[product_id] for product_id in product_ids if product_id in recommendations]
        return ForecastRunComparisonMetrics(
            mae=mae,
            mape_pct=mape_pct,
            wmape_pct=wmape_pct,
            avg_confidence=float(mean(confidences)) if confidences else None,
            stockout_within_horizon_count=sum(1 for row in rows if row.predicted_stockout_date is not None),
            reorder_required_count=sum(1 for row in rows if int(row.suggested_qty or 0) > 0),
            total_suggested_reorder_qty=sum(int(row.suggested_qty or 0) for row in rows),
        )

    @staticmethod
    def _comparison_verdict(
        *,
        comparable_points: int,
        baseline: ForecastRunComparisonMetrics,
        candidate: ForecastRunComparisonMetrics,
    ) -> str:
        if comparable_points <= 0 or baseline.wmape_pct is None or candidate.wmape_pct is None:
            return "insufficient_actuals"

        wmape_delta = candidate.wmape_pct - baseline.wmape_pct
        mae_delta = (
            None
            if baseline.mae is None or candidate.mae is None
            else candidate.mae - baseline.mae
        )
        confidence_delta = (
            None
            if baseline.avg_confidence is None or candidate.avg_confidence is None
            else candidate.avg_confidence - baseline.avg_confidence
        )

        if wmape_delta < -0.1 and (mae_delta is None or mae_delta <= 0.0) and (confidence_delta is None or confidence_delta >= 0.0):
            return "improved"
        if wmape_delta > 0.1 and (mae_delta is None or mae_delta >= 0.0) and (confidence_delta is None or confidence_delta <= 0.0):
            return "degraded"
        return "mixed"

    @staticmethod
    def _validation_row_float(row: dict[str, object] | None, key: str, *, fallback_key: str | None = None) -> float | None:
        if row is None:
            return None
        value = row.get(key)
        if value is None and fallback_key is not None:
            value = row.get(fallback_key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _validation_raw_candidate_wmape(cls, row: dict[str, object] | None) -> float | None:
        return cls._validation_row_float(
            row,
            "candidate_model_wmape_pct",
            fallback_key="model_wmape_pct",
        )

    @staticmethod
    def _validation_candidate_model_name(row: dict[str, object] | None) -> str | None:
        if row is None:
            return None
        candidate_model_name = str(row.get("candidate_model_name") or "").strip()
        if candidate_model_name:
            return candidate_model_name
        selected_model_name = str(row.get("model_name") or "").strip()
        return selected_model_name or None

    @staticmethod
    def _validation_fallback_reason(
        row: dict[str, object] | None,
        fallback_map: dict[str, str],
    ) -> str | None:
        if row is None:
            return None
        row_reason = str(row.get("fallback_reason") or "").strip()
        if row_reason:
            return row_reason
        sku = str(row.get("sku") or "").strip()
        return fallback_map.get(sku) or None

    @staticmethod
    def _validation_selected_strategy_action(
        row: dict[str, object] | None,
        *,
        fallback_reason: str | None,
    ) -> str | None:
        if row is None:
            return None
        action = str(row.get("selected_strategy_action") or "").strip()
        if action:
            return action
        selected_model_name = str(row.get("model_name") or "").strip()
        if selected_model_name == "BaselineFallback" or fallback_reason:
            return "baseline_fallback"
        return "none"

    @classmethod
    def _build_validation_snapshot(
        cls,
        summary: dict[str, object],
        rows: list[dict[str, object]],
        *,
        fallback_map: dict[str, str],
    ) -> ForecastRunValidationSnapshot | None:
        enriched_summary = dict(summary)

        evaluated_rows = [
            row
            for row in rows
            if cls._validation_row_float(row, "model_wmape_pct") is not None
            and cls._validation_row_float(row, "baseline_wmape_pct") is not None
        ]
        raw_candidate_rows = [
            row
            for row in rows
            if cls._validation_raw_candidate_wmape(row) is not None
            and cls._validation_row_float(row, "baseline_wmape_pct") is not None
        ]
        raw_candidate_wmapes = [
            value
            for row in raw_candidate_rows
            if (value := cls._validation_raw_candidate_wmape(row)) is not None
        ]
        raw_candidate_baselines = [
            value
            for row in raw_candidate_rows
            if (value := cls._validation_row_float(row, "baseline_wmape_pct")) is not None
        ]

        fallback_count = 0
        mature_evaluated_skus = 0
        mature_raw_candidate_win_count = 0
        for row in rows:
            fallback_reason = cls._validation_fallback_reason(row, fallback_map)
            action = cls._validation_selected_strategy_action(row, fallback_reason=fallback_reason)
            if action == "baseline_fallback":
                fallback_count += 1

            data_tier = str(row.get("data_tier") or "").strip()
            raw_candidate_wmape = cls._validation_raw_candidate_wmape(row)
            baseline_wmape = cls._validation_row_float(row, "baseline_wmape_pct")
            if data_tier == "mature" and raw_candidate_wmape is not None and baseline_wmape is not None:
                mature_evaluated_skus += 1
                if raw_candidate_wmape <= baseline_wmape:
                    mature_raw_candidate_win_count += 1

        evaluated_skus = int(enriched_summary.get("evaluated_skus") or len(evaluated_rows))
        skipped_skus = int(enriched_summary.get("skipped_skus") or max(0, len(rows) - evaluated_skus))
        enriched_summary.setdefault("method", "lead_time_backtest")
        enriched_summary["evaluated_skus"] = evaluated_skus
        enriched_summary["skipped_skus"] = skipped_skus
        enriched_summary["raw_candidate_wmape_pct"] = cls._average_or_none(raw_candidate_wmapes)
        enriched_summary["raw_candidate_wmape_improvement_pct"] = cls._improvement_pct(
            cls._average_or_none(raw_candidate_wmapes),
            cls._average_or_none(raw_candidate_baselines),
        )
        enriched_summary["selected_strategy_fallback_count"] = fallback_count
        enriched_summary["selected_strategy_fallback_rate_pct"] = (
            None
            if evaluated_skus <= 0
            else float(fallback_count / evaluated_skus) * 100.0
        )
        enriched_summary["mature_evaluated_skus"] = mature_evaluated_skus
        enriched_summary["mature_raw_candidate_win_count"] = mature_raw_candidate_win_count
        enriched_summary["mature_raw_candidate_win_rate_pct"] = (
            None
            if mature_evaluated_skus <= 0
            else float(mature_raw_candidate_win_count / mature_evaluated_skus) * 100.0
        )

        try:
            return ForecastRunValidationSnapshot.model_validate(enriched_summary)
        except Exception:
            return None

    def _load_run_validation_report(
        self,
        run: ForecastRun,
    ) -> tuple[ForecastRunValidationSnapshot | None, list[dict[str, object]]]:
        report_name = self._parse_run_note_value(run.notes, "validation_report")
        if report_name is None:
            return None, []

        report_path = Path(__file__).resolve().parents[2] / "data" / report_name
        if not report_path.exists():
            return None, []

        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, []

        summary = payload.get("summary")
        rows_payload = payload.get("rows")
        rows = [row for row in rows_payload if isinstance(row, dict)] if isinstance(rows_payload, list) else []
        if not isinstance(summary, dict):
            summary = {}

        fallback_map = self._parse_run_note_map(run.notes, "fallback")
        return self._build_validation_snapshot(summary, rows, fallback_map=fallback_map), rows

    @staticmethod
    def _validation_comparison_verdict(
        baseline: ForecastRunValidationSnapshot | None,
        candidate: ForecastRunValidationSnapshot | None,
    ) -> str:
        if baseline is None or candidate is None:
            return "unavailable"
        if baseline.model_wmape_pct is None or candidate.model_wmape_pct is None:
            return "unavailable"

        wmape_delta = candidate.model_wmape_pct - baseline.model_wmape_pct
        improvement_delta = (
            None
            if baseline.wmape_improvement_pct is None or candidate.wmape_improvement_pct is None
            else candidate.wmape_improvement_pct - baseline.wmape_improvement_pct
        )

        if wmape_delta < -0.1 and (improvement_delta is None or improvement_delta >= 0.1):
            return "improved"
        if wmape_delta > 0.1 and (improvement_delta is None or improvement_delta <= -0.1):
            return "degraded"
        return "mixed"

    @staticmethod
    def _build_validation_delta(
        baseline: ForecastRunValidationSnapshot | None,
        candidate: ForecastRunValidationSnapshot | None,
    ) -> ForecastRunValidationDelta | None:
        if baseline is None or candidate is None:
            return None
        return ForecastRunValidationDelta(
            evaluated_skus=candidate.evaluated_skus - baseline.evaluated_skus,
            skipped_skus=candidate.skipped_skus - baseline.skipped_skus,
            model_wmape_pct=(
                None
                if baseline.model_wmape_pct is None or candidate.model_wmape_pct is None
                else candidate.model_wmape_pct - baseline.model_wmape_pct
            ),
            baseline_wmape_pct=(
                None
                if baseline.baseline_wmape_pct is None or candidate.baseline_wmape_pct is None
                else candidate.baseline_wmape_pct - baseline.baseline_wmape_pct
            ),
            wmape_improvement_pct=(
                None
                if baseline.wmape_improvement_pct is None or candidate.wmape_improvement_pct is None
                else candidate.wmape_improvement_pct - baseline.wmape_improvement_pct
            ),
            raw_candidate_wmape_pct=(
                None
                if baseline.raw_candidate_wmape_pct is None or candidate.raw_candidate_wmape_pct is None
                else candidate.raw_candidate_wmape_pct - baseline.raw_candidate_wmape_pct
            ),
            raw_candidate_wmape_improvement_pct=(
                None
                if baseline.raw_candidate_wmape_improvement_pct is None
                or candidate.raw_candidate_wmape_improvement_pct is None
                else candidate.raw_candidate_wmape_improvement_pct - baseline.raw_candidate_wmape_improvement_pct
            ),
            total_windows_evaluated=candidate.total_windows_evaluated - baseline.total_windows_evaluated,
            model_win_count=candidate.model_win_count - baseline.model_win_count,
            model_win_rate_pct=(
                None
                if baseline.model_win_rate_pct is None or candidate.model_win_rate_pct is None
                else candidate.model_win_rate_pct - baseline.model_win_rate_pct
            ),
            selected_strategy_fallback_count=(
                candidate.selected_strategy_fallback_count - baseline.selected_strategy_fallback_count
            ),
            selected_strategy_fallback_rate_pct=(
                None
                if baseline.selected_strategy_fallback_rate_pct is None
                or candidate.selected_strategy_fallback_rate_pct is None
                else candidate.selected_strategy_fallback_rate_pct - baseline.selected_strategy_fallback_rate_pct
            ),
            mature_evaluated_skus=candidate.mature_evaluated_skus - baseline.mature_evaluated_skus,
            mature_raw_candidate_win_count=(
                candidate.mature_raw_candidate_win_count - baseline.mature_raw_candidate_win_count
            ),
            mature_raw_candidate_win_rate_pct=(
                None
                if baseline.mature_raw_candidate_win_rate_pct is None
                or candidate.mature_raw_candidate_win_rate_pct is None
                else candidate.mature_raw_candidate_win_rate_pct - baseline.mature_raw_candidate_win_rate_pct
            ),
        )

    def _build_validation_sku_rows(
        self,
        *,
        baseline_run: ForecastRun,
        candidate_run: ForecastRun,
        baseline_rows: list[dict[str, object]],
        candidate_rows: list[dict[str, object]],
    ) -> list[ForecastRunValidationSkuRow]:
        baseline_by_sku = {
            str(row.get("sku")).strip(): row
            for row in baseline_rows
            if str(row.get("sku") or "").strip()
        }
        candidate_by_sku = {
            str(row.get("sku")).strip(): row
            for row in candidate_rows
            if str(row.get("sku") or "").strip()
        }
        if not baseline_by_sku and not candidate_by_sku:
            return []

        baseline_fallback_map = self._parse_run_note_map(baseline_run.notes, "fallback")
        candidate_fallback_map = self._parse_run_note_map(candidate_run.notes, "fallback")

        rows: list[ForecastRunValidationSkuRow] = []
        for sku in sorted(set(baseline_by_sku).union(candidate_by_sku)):
            baseline_row = baseline_by_sku.get(sku)
            candidate_row = candidate_by_sku.get(sku)
            product_id_value: int | None = None
            product_source = candidate_row or baseline_row
            if product_source is not None:
                try:
                    raw_product_id = product_source.get("product_id")
                    product_id_value = None if raw_product_id is None else int(raw_product_id)
                except (TypeError, ValueError):
                    product_id_value = None

            baseline_fallback_reason = self._validation_fallback_reason(baseline_row, baseline_fallback_map)
            candidate_fallback_reason = self._validation_fallback_reason(candidate_row, candidate_fallback_map)

            baseline_selected_wmape = self._validation_row_float(baseline_row, "model_wmape_pct")
            candidate_selected_wmape = self._validation_row_float(candidate_row, "model_wmape_pct")
            baseline_raw_candidate_wmape = self._validation_raw_candidate_wmape(baseline_row)
            candidate_raw_candidate_wmape = self._validation_raw_candidate_wmape(candidate_row)
            baseline_baseline_wmape = self._validation_row_float(baseline_row, "baseline_wmape_pct")
            candidate_baseline_wmape = self._validation_row_float(candidate_row, "baseline_wmape_pct")

            baseline_raw_gap = self._float_delta(baseline_raw_candidate_wmape, baseline_baseline_wmape)
            candidate_raw_gap = self._float_delta(candidate_raw_candidate_wmape, candidate_baseline_wmape)

            rows.append(
                ForecastRunValidationSkuRow(
                    product_id=product_id_value,
                    sku=sku,
                    baseline_data_tier=str(baseline_row.get("data_tier") or "").strip() or None
                    if baseline_row is not None
                    else None,
                    candidate_data_tier=str(candidate_row.get("data_tier") or "").strip() or None
                    if candidate_row is not None
                    else None,
                    baseline_quality_status=str(baseline_row.get("quality_status") or "").strip() or None
                    if baseline_row is not None
                    else None,
                    candidate_quality_status=str(candidate_row.get("quality_status") or "").strip() or None
                    if candidate_row is not None
                    else None,
                    baseline_selected_strategy_action=self._validation_selected_strategy_action(
                        baseline_row,
                        fallback_reason=baseline_fallback_reason,
                    ),
                    candidate_selected_strategy_action=self._validation_selected_strategy_action(
                        candidate_row,
                        fallback_reason=candidate_fallback_reason,
                    ),
                    baseline_fallback_reason=baseline_fallback_reason,
                    candidate_fallback_reason=candidate_fallback_reason,
                    baseline_selected_model_name=str(baseline_row.get("model_name") or "").strip() or None
                    if baseline_row is not None
                    else None,
                    candidate_selected_model_name=str(candidate_row.get("model_name") or "").strip() or None
                    if candidate_row is not None
                    else None,
                    baseline_raw_candidate_model_name=self._validation_candidate_model_name(baseline_row),
                    candidate_raw_candidate_model_name=self._validation_candidate_model_name(candidate_row),
                    baseline_selected_wmape_pct=baseline_selected_wmape,
                    candidate_selected_wmape_pct=candidate_selected_wmape,
                    selected_wmape_delta=self._float_delta(candidate_selected_wmape, baseline_selected_wmape),
                    baseline_raw_candidate_wmape_pct=baseline_raw_candidate_wmape,
                    candidate_raw_candidate_wmape_pct=candidate_raw_candidate_wmape,
                    raw_candidate_wmape_delta=self._float_delta(
                        candidate_raw_candidate_wmape,
                        baseline_raw_candidate_wmape,
                    ),
                    baseline_baseline_wmape_pct=baseline_baseline_wmape,
                    candidate_baseline_wmape_pct=candidate_baseline_wmape,
                    baseline_raw_candidate_gap_vs_baseline_pct=baseline_raw_gap,
                    candidate_raw_candidate_gap_vs_baseline_pct=candidate_raw_gap,
                    raw_candidate_gap_vs_baseline_delta=self._float_delta(candidate_raw_gap, baseline_raw_gap),
                )
            )

        rows.sort(
            key=lambda row: (
                0 if (row.candidate_data_tier or row.baseline_data_tier) == "mature" else 1,
                0 if row.candidate_selected_strategy_action == "baseline_fallback" else 1,
                -(
                    row.candidate_raw_candidate_gap_vs_baseline_pct
                    if row.candidate_raw_candidate_gap_vs_baseline_pct is not None
                    else -1_000_000.0
                ),
                row.sku,
            )
        )
        return rows

    def get_forecast_report_comparison(
        self,
        *,
        baseline_run_id: int | None = None,
        candidate_run_id: int | None = None,
    ) -> ForecastRunComparisonResponse:
        baseline_run, candidate_run = self._resolve_forecast_run_pair(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
        )

        baseline_meta, baseline_forecasts, baseline_totals = self._load_run_forecast_values(baseline_run.id)
        candidate_meta, candidate_forecasts, candidate_totals = self._load_run_forecast_values(candidate_run.id)
        baseline_recommendations = self._load_run_recommendations(baseline_run.id)
        candidate_recommendations = self._load_run_recommendations(candidate_run.id)

        shared_product_ids = sorted(set(baseline_forecasts).intersection(candidate_forecasts))
        comparable_dates: list[date] = []
        actual_product_ids: list[int] = []
        today = date.today()

        for product_id in shared_product_ids:
            shared_dates = sorted(set(baseline_forecasts[product_id]).intersection(candidate_forecasts[product_id]))
            realized_dates = [forecast_date for forecast_date in shared_dates if forecast_date <= today]
            if realized_dates:
                actual_product_ids.append(product_id)
                comparable_dates.extend(realized_dates)

        actuals_lookup: dict[tuple[int, date], float] = {}
        if comparable_dates and actual_product_ids:
            actuals_lookup = self._load_actual_units_lookup(
                product_ids=sorted(set(actual_product_ids)),
                start_date=min(comparable_dates),
                end_date=max(comparable_dates),
            )

        baseline_actual: list[float] = []
        baseline_predicted: list[float] = []
        candidate_predicted: list[float] = []
        comparable_sku_ids: list[int] = []

        for product_id in shared_product_ids:
            shared_dates = sorted(set(baseline_forecasts[product_id]).intersection(candidate_forecasts[product_id]))
            realized_dates = [forecast_date for forecast_date in shared_dates if forecast_date <= today]
            if not realized_dates:
                continue
            comparable_sku_ids.append(product_id)
            for forecast_date in realized_dates:
                baseline_actual.append(float(actuals_lookup.get((product_id, forecast_date), 0.0)))
                baseline_predicted.append(float(baseline_forecasts[product_id][forecast_date]))
                candidate_predicted.append(float(candidate_forecasts[product_id][forecast_date]))

        baseline_metrics = self._build_run_comparison_metrics(
            actual=baseline_actual,
            predicted=baseline_predicted,
            recommendations=baseline_recommendations,
            product_ids=shared_product_ids,
        )
        candidate_metrics = self._build_run_comparison_metrics(
            actual=baseline_actual,
            predicted=candidate_predicted,
            recommendations=candidate_recommendations,
            product_ids=shared_product_ids,
        )

        sku_rows: list[ForecastRunComparisonSkuRow] = []
        for product_id in shared_product_ids:
            meta = candidate_meta.get(product_id) or baseline_meta.get(product_id) or {}
            baseline_recommendation = baseline_recommendations.get(product_id)
            candidate_recommendation = candidate_recommendations.get(product_id)
            baseline_confidence = (
                float(baseline_recommendation.confidence_score)
                if baseline_recommendation is not None and baseline_recommendation.confidence_score is not None
                else None
            )
            candidate_confidence = (
                float(candidate_recommendation.confidence_score)
                if candidate_recommendation is not None and candidate_recommendation.confidence_score is not None
                else None
            )
            baseline_suggested_qty = int(baseline_recommendation.suggested_qty) if baseline_recommendation is not None else 0
            candidate_suggested_qty = int(candidate_recommendation.suggested_qty) if candidate_recommendation is not None else 0
            baseline_total = baseline_totals.get(product_id)
            candidate_total = candidate_totals.get(product_id)
            sku_rows.append(
                ForecastRunComparisonSkuRow(
                    product_id=product_id,
                    sku=str(meta.get("sku") or f"product-{product_id}"),
                    name=str(meta.get("name") or ""),
                    baseline_predicted_units_total=baseline_total,
                    candidate_predicted_units_total=candidate_total,
                    predicted_units_total_delta=(
                        None
                        if baseline_total is None or candidate_total is None
                        else float(candidate_total - baseline_total)
                    ),
                    baseline_suggested_qty=baseline_suggested_qty,
                    candidate_suggested_qty=candidate_suggested_qty,
                    suggested_qty_delta=candidate_suggested_qty - baseline_suggested_qty,
                    baseline_confidence_score=baseline_confidence,
                    candidate_confidence_score=candidate_confidence,
                    confidence_score_delta=self._float_delta(candidate_confidence, baseline_confidence),
                    baseline_predicted_stockout_date=(
                        baseline_recommendation.predicted_stockout_date if baseline_recommendation is not None else None
                    ),
                    candidate_predicted_stockout_date=(
                        candidate_recommendation.predicted_stockout_date if candidate_recommendation is not None else None
                    ),
                )
            )

        sku_rows.sort(key=lambda row: (abs(row.suggested_qty_delta), abs(row.confidence_score_delta or 0.0)), reverse=True)

        metrics_window = ForecastRunComparisonWindow(
            comparable_skus=len(comparable_sku_ids),
            comparable_points=len(baseline_actual),
            actuals_start=min(comparable_dates) if comparable_dates else None,
            actuals_end=max(comparable_dates) if comparable_dates else None,
        )
        verdict = self._comparison_verdict(
            comparable_points=metrics_window.comparable_points,
            baseline=baseline_metrics,
            candidate=candidate_metrics,
        )
        baseline_validation, baseline_validation_rows = self._load_run_validation_report(baseline_run)
        candidate_validation, candidate_validation_rows = self._load_run_validation_report(candidate_run)
        validation = None
        if baseline_validation is not None or candidate_validation is not None:
            validation = ForecastRunValidationComparison(
                verdict=self._validation_comparison_verdict(baseline_validation, candidate_validation),
                baseline=baseline_validation,
                candidate=candidate_validation,
                delta=self._build_validation_delta(baseline_validation, candidate_validation),
            )
        validation_sku_rows = self._build_validation_sku_rows(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            baseline_rows=baseline_validation_rows,
            candidate_rows=candidate_validation_rows,
        )

        return ForecastRunComparisonResponse(
            baseline_run=ForecastRunComparisonRun(
                run_id=baseline_run.id,
                run_at=baseline_run.run_at,
                horizon_days=baseline_run.horizon_days,
                model_version=baseline_run.model_version or "n/a",
            ),
            candidate_run=ForecastRunComparisonRun(
                run_id=candidate_run.id,
                run_at=candidate_run.run_at,
                horizon_days=candidate_run.horizon_days,
                model_version=candidate_run.model_version or "n/a",
            ),
            verdict=verdict,
            metrics=metrics_window,
            baseline=baseline_metrics,
            candidate=candidate_metrics,
            delta=ForecastRunComparisonDelta(
                mae=self._float_delta(candidate_metrics.mae, baseline_metrics.mae),
                mape_pct=self._float_delta(candidate_metrics.mape_pct, baseline_metrics.mape_pct),
                wmape_pct=self._float_delta(candidate_metrics.wmape_pct, baseline_metrics.wmape_pct),
                avg_confidence=self._float_delta(candidate_metrics.avg_confidence, baseline_metrics.avg_confidence),
                stockout_within_horizon_count=(
                    candidate_metrics.stockout_within_horizon_count - baseline_metrics.stockout_within_horizon_count
                ),
                reorder_required_count=candidate_metrics.reorder_required_count - baseline_metrics.reorder_required_count,
                total_suggested_reorder_qty=(
                    candidate_metrics.total_suggested_reorder_qty - baseline_metrics.total_suggested_reorder_qty
                ),
            ),
            validation=validation,
            validation_sku_rows=validation_sku_rows,
            sku_rows=sku_rows,
        )

    def get_forecast_report(
        self,
        *,
        include_details: bool = False,
        evaluation_days: int = 7,
        run_id: int | None = None,
    ) -> ForecastReportResponse:
        run_stmt = select(ForecastRun)
        if run_id is not None:
            run_stmt = run_stmt.where(ForecastRun.id == run_id)
        run_stmt = run_stmt.order_by(ForecastRun.id.desc())
        run = self.db.scalars(run_stmt).first()
        if run is None:
            raise ValueError("No forecast run found. Run the forecast job first.")

        forecast_totals_subquery = (
            select(
                SkuForecast.product_id.label("product_id"),
                func.sum(SkuForecast.predicted_units).label("predicted_units_total"),
            )
            .where(SkuForecast.run_id == run.id)
            .group_by(SkuForecast.product_id)
            .subquery()
        )

        statement = (
            select(
                Product,
                ReorderRecommendation,
                InventoryBalance.on_hand_qty,
                Supplier.lead_time_days_default,
                forecast_totals_subquery.c.predicted_units_total,
            )
            .join(ReorderRecommendation, ReorderRecommendation.product_id == Product.id)
            .outerjoin(InventoryBalance, InventoryBalance.product_id == Product.id)
            .outerjoin(Supplier, Supplier.id == Product.supplier_id)
            .outerjoin(forecast_totals_subquery, forecast_totals_subquery.c.product_id == Product.id)
            .where(ReorderRecommendation.run_id == run.id)
            .order_by(
                ReorderRecommendation.predicted_stockout_date.is_(None).asc(),
                ReorderRecommendation.predicted_stockout_date.asc(),
                Product.sku.asc(),
            )
        )
        rows = self.db.execute(statement).all()
        gated_map = self._parse_run_note_map(run.notes, "gated")
        fallback_map = self._parse_run_note_map(run.notes, "fallback")
        qa_summary = self._parse_run_note_value(run.notes, "qa")
        qa_report = self._parse_run_note_value(run.notes, "qa_report")

        explainability_rows: list[ForecastExplainabilityRow] = []
        for product, recommendation, on_hand_qty, lead_time_days_default, predicted_units_total in rows:
            on_hand = int(on_hand_qty or 0)
            lead_time_days = max(1, int(lead_time_days_default or 7))
            predicted_total = float(predicted_units_total or 0.0)
            avg_daily_units = predicted_total / max(run.horizon_days, 1)
            confidence_score = (
                float(recommendation.confidence_score)
                if recommendation.confidence_score is not None
                else None
            )

            row = ForecastExplainabilityRow(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                on_hand_qty=on_hand,
                lead_time_days=lead_time_days,
                safety_stock=int(product.safety_stock),
                predicted_30d_units=predicted_total,
                avg_daily_units=avg_daily_units,
                predicted_stockout_date=recommendation.predicted_stockout_date,
                reorder_point=int(recommendation.reorder_point),
                suggested_qty=int(recommendation.suggested_qty),
                confidence_score=confidence_score,
                explanation="",
            )
            gate_reason = gated_map.get(product.sku)
            fallback_reason = fallback_map.get(product.sku)
            if gate_reason:
                row.explanation = (
                    f"Recommendation gated due to insufficient data quality ({gate_reason}). "
                    "Collect more sales history before enabling automatic reorder decisions."
                )
            elif fallback_reason:
                row.explanation = (
                    f"Recommendation generated via baseline fallback ({fallback_reason}). "
                    "Model underperformed baseline on lead-time backtest, so this quantity is conservative."
                )
            else:
                row.explanation = self._build_reorder_explanation(row)
            explainability_rows.append(row)

        product_ids = [row.product_id for row in explainability_rows]
        mature_product_id_set: set[int] = set()
        for product_id in product_ids:
            history = self._load_sales_history_dense(product_id)
            stock_movements = self._load_stock_movements(product_id)
            censored_dates = estimate_censored_sales_dates(
                history[["date", "units"]],
                stock_movements=stock_movements,
            )
            if self._is_mature_history(history, censored_dates=censored_dates):
                mature_product_id_set.add(product_id)

        for row in explainability_rows:
            row.data_tier = "mature" if row.product_id in mature_product_id_set else "non_mature"

        mature_product_ids = [product_id for product_id in product_ids if product_id in mature_product_id_set]
        non_mature_product_ids = [product_id for product_id in product_ids if product_id not in mature_product_id_set]

        confidence_values = [row.confidence_score for row in explainability_rows if row.confidence_score is not None]
        high_confidence_rows = [
            row
            for row in explainability_rows
            if row.confidence_score is not None and float(row.confidence_score) >= 0.70
        ]
        high_confidence_mature_rows = [row for row in high_confidence_rows if row.data_tier == "mature"]
        high_confidence_non_mature_rows = [row for row in high_confidence_rows if row.data_tier == "non_mature"]
        summary = ForecastReportSummary(
            sku_count=len(explainability_rows),
            recommendations_count=len(explainability_rows),
            stockout_within_horizon_count=sum(1 for row in explainability_rows if row.predicted_stockout_date is not None),
            reorder_required_count=sum(1 for row in explainability_rows if row.suggested_qty > 0),
            total_suggested_reorder_qty=sum(row.suggested_qty for row in explainability_rows),
            avg_confidence=float(mean(confidence_values)) if confidence_values else None,
            mature_sku_count=len(mature_product_ids),
            non_mature_sku_count=len(non_mature_product_ids),
            high_confidence_count=len(high_confidence_rows),
            high_confidence_mature_count=len(high_confidence_mature_rows),
            high_confidence_non_mature_count=len(high_confidence_non_mature_rows),
        )
        mature_sku_criteria = self._mature_sku_criteria_text()

        evaluation_full = self._evaluate_forecast_quality(
            product_ids,
            evaluation_days=evaluation_days,
        )
        evaluation_mature = self._evaluate_forecast_quality(
            mature_product_ids,
            evaluation_days=evaluation_days,
        )
        evaluation_non_mature = self._evaluate_forecast_quality(
            non_mature_product_ids,
            evaluation_days=evaluation_days,
        )
        markdown_report = self._render_markdown_report(
            run,
            summary,
            evaluation_full,
            evaluation_mature,
            evaluation_non_mature,
            mature_sku_criteria,
            qa_summary,
            qa_report,
            explainability_rows,
        )

        return ForecastReportResponse(
            run_id=run.id,
            run_at=run.run_at,
            horizon_days=run.horizon_days,
            model_version=run.model_version or "n/a",
            summary=summary,
            evaluation_full=evaluation_full,
            evaluation_mature=evaluation_mature,
            evaluation_non_mature=evaluation_non_mature,
            mature_sku_criteria=mature_sku_criteria,
            evaluation=evaluation_full,
            qa_summary=qa_summary,
            qa_report=qa_report,
            markdown_report=markdown_report,
            explainability_rows=explainability_rows if include_details else [],
        )

    def _latest_competitor_prices_for_product(self, product_id: int) -> list[ItemPriceBenchmark]:
        statement = (
            select(
                CompetitorPriceSnapshot.source_id,
                CompetitorPriceSnapshot.competitor_price,
                CompetitorPriceSnapshot.scraped_at,
                CompetitorSource.name,
            )
            .join(CompetitorSource, CompetitorSource.id == CompetitorPriceSnapshot.source_id)
            .where(CompetitorPriceSnapshot.product_id == product_id)
            .order_by(
                CompetitorPriceSnapshot.source_id.asc(),
                CompetitorPriceSnapshot.scraped_at.desc(),
            )
        )
        rows = self.db.execute(statement).all()

        latest_by_source: dict[int, ItemPriceBenchmark] = {}
        for row in rows:
            if row.source_id in latest_by_source:
                continue
            latest_by_source[row.source_id] = ItemPriceBenchmark(
                source_name=row.name,
                price=Decimal(str(row.competitor_price)),
            )

        return sorted(latest_by_source.values(), key=lambda item: item.price)

    def get_item_forecast_detail(self, product_id: int, *, history_days: int = 365) -> ItemForecastDetail:
        product = self.db.get(Product, product_id)
        if product is None or not product.active:
            raise ValueError("Product not found.")

        latest_run_id = self.db.scalar(
            select(func.max(ReorderRecommendation.run_id)).where(ReorderRecommendation.product_id == product.id)
        )
        if latest_run_id is None:
            raise ValueError("No forecast recommendation found for this item. Run forecast job first.")

        run = self.db.get(ForecastRun, latest_run_id)
        if run is None:
            raise ValueError("Forecast run metadata not found.")

        recommendation = self.db.scalars(
            select(ReorderRecommendation).where(
                ReorderRecommendation.run_id == latest_run_id,
                ReorderRecommendation.product_id == product.id,
            )
        ).first()
        if recommendation is None:
            raise ValueError("No reorder recommendation found for this item.")

        on_hand = int(self.db.scalar(select(InventoryBalance.on_hand_qty).where(InventoryBalance.product_id == product.id)) or 0)

        forecast_rows = list(
            self.db.execute(
                select(SkuForecast.forecast_date, SkuForecast.predicted_units)
                .where(SkuForecast.run_id == latest_run_id, SkuForecast.product_id == product.id)
                .order_by(SkuForecast.forecast_date.asc())
            ).all()
        )
        predicted_total = float(sum(float(row.predicted_units or 0) for row in forecast_rows))
        horizon_days = max(run.horizon_days, 1)
        predicted_per_month = (predicted_total / horizon_days) * 30

        history_dense = self._load_sales_history_dense(product.id).tail(max(1, history_days))
        demand_points: list[ItemDemandPoint] = [
            ItemDemandPoint(
                date=(row.date if isinstance(row.date, date) else date.fromisoformat(str(row.date))),
                units=float(row.units),
                kind="history",
            )
            for row in history_dense.itertuples(index=False)
        ]
        demand_points.extend(
            ItemDemandPoint(
                date=row.forecast_date,
                units=float(row.predicted_units or 0),
                kind="forecast",
            )
            for row in forecast_rows
        )

        confidence_pct = (
            float(recommendation.confidence_score) * 100 if recommendation.confidence_score is not None else None
        )
        gated_map = self._parse_run_note_map(run.notes, "gated")
        fallback_map = self._parse_run_note_map(run.notes, "fallback")
        gate_reason = gated_map.get(product.sku)
        fallback_reason = fallback_map.get(product.sku)

        if gate_reason:
            days_until_stockout = None
            when_to_buy_message = (
                "Insufficient data quality for automatic reorder recommendations. "
                f"Reason: {gate_reason}. Continue collecting sales history and rerun forecast."
            )
        elif fallback_reason:
            days_until_stockout = None if recommendation.predicted_stockout_date is None else (
                recommendation.predicted_stockout_date - date.today()
            ).days
            when_to_buy_message = (
                "Baseline fallback recommendation applied. "
                f"Reason: {fallback_reason}. Use this quantity as a conservative temporary guide."
            )
        elif recommendation.predicted_stockout_date is None:
            days_until_stockout = None
            when_to_buy_message = "Stock level is healthy in the current forecast horizon."
        else:
            days_until_stockout = (recommendation.predicted_stockout_date - date.today()).days
            if days_until_stockout <= 0:
                when_to_buy_message = (
                    f"Running low! Stockout risk is immediate. Order {recommendation.suggested_qty} units now."
                )
            else:
                when_to_buy_message = (
                    f"Running low! Only {days_until_stockout} days left. "
                    f"Order {recommendation.suggested_qty} units now."
                )

        competitor_benchmarks = self._latest_competitor_prices_for_product(product.id)
        market_avg_price: Decimal | None = None
        difference_pct: Decimal | None = None
        suggested_price: Decimal | None = None

        if competitor_benchmarks:
            benchmark_total = sum((benchmark.price for benchmark in competitor_benchmarks), Decimal("0"))
            market_avg_price = (benchmark_total / Decimal(len(competitor_benchmarks))).quantize(Decimal("0.01"))
            if market_avg_price > 0:
                difference_pct = (((product.sell_price - market_avg_price) / market_avg_price) * Decimal("100")).quantize(
                    Decimal("0.01")
                )
                if difference_pct > Decimal("5.00"):
                    suggested_price = (market_avg_price * Decimal("1.02")).quantize(Decimal("0.01"))

        return ItemForecastDetail(
            product_id=product.id,
            sku=product.sku,
            name=product.name,
            forecast_horizon_days=run.horizon_days,
            predicted_per_month=predicted_per_month,
            in_stock=on_hand,
            reorder_qty=recommendation.suggested_qty,
            confidence_pct=confidence_pct,
            predicted_stockout_date=recommendation.predicted_stockout_date,
            days_until_stockout=days_until_stockout,
            when_to_buy_message=when_to_buy_message,
            demand_points=demand_points,
            price_analysis=ItemPriceAnalysis(
                store_price=product.sell_price,
                market_avg_price=market_avg_price,
                difference_pct=difference_pct,
                suggested_price=suggested_price,
                competitor_benchmarks=competitor_benchmarks[:6],
            ),
        )
