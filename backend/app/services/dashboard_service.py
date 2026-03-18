from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from math import comb
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
    forecast_product_daily_units_with_diagnostics,
)
from app.schemas.dashboard import (
    DashboardKpis,
    ForecastEvaluationMetrics,
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
            minutes_since_latest = (
                int((now_utc - latest_scraped_at).total_seconds() // 60)
                if latest_scraped_at is not None
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
                and last_run_attempted > 0
                and last_run_inserted == 0
                and consecutive_zero_runs >= 2
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
                    latest_scraped_at=latest_scraped_at,
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
        full_dates = pd.date_range(start=raw["date"].min(), end=raw["date"].max(), freq="D").date
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
    def _mature_history_thresholds() -> tuple[int, int, float]:
        return (
            max(MIN_HISTORY_DAYS * 2, 42),
            max(MIN_NON_ZERO_DAYS * 2, 12),
            max(MIN_NON_ZERO_RATIO * 2.0, 0.18),
        )

    @classmethod
    def _mature_sku_criteria_text(cls) -> str:
        min_history_days, min_non_zero_days, min_non_zero_ratio = cls._mature_history_thresholds()
        return (
            f"history_days>={min_history_days}, "
            f"non_zero_days>={min_non_zero_days}, "
            f"non_zero_ratio>={min_non_zero_ratio * 100:.1f}%"
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

        min_history_days, min_non_zero_days, min_non_zero_ratio = cls._mature_history_thresholds()
        working_history = history.copy()
        if censored_dates:
            censored_date_values = {pd.Timestamp(value).date() for value in censored_dates}
            history_dates = pd.to_datetime(working_history["date"]).dt.date
            working_history = working_history.loc[~history_dates.isin(censored_date_values)].copy()
            if working_history.empty:
                return False

        units = working_history["units"].astype(float)
        history_days = len(units)
        non_zero_days = int((units > 0.0).sum())
        non_zero_ratio = float(non_zero_days / history_days) if history_days > 0 else 0.0

        return (
            history_days >= min_history_days
            and non_zero_days >= min_non_zero_days
            and non_zero_ratio >= min_non_zero_ratio
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
                cutoff = pd.to_datetime(train["date"]).max()
                movement_dates = pd.to_datetime(stock_movements["occurred_at"]).dt.normalize()
                train_stock_movements = stock_movements.loc[movement_dates <= cutoff].copy()

            lead_time_wmape, lead_time_baseline_wmape = _lead_time_operational_backtest(
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
            )
            gate_reason = _recommendation_gate_reason(
                result.diagnostics.selected_score,
                quality,
                confidence,
                lead_time_wmape_pct=lead_time_wmape,
                lead_time_baseline_wmape_pct=lead_time_baseline_wmape,
            )
            action = _recommendation_action(_parse_reason_tokens(gate_reason))

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
        mature_sku_criteria: str,
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
            "",
            "## Summary",
            f"- Forecasted SKUs: {summary.sku_count}",
            f"- Recommendations generated: {summary.recommendations_count}",
            f"- SKUs with stockout risk in horizon: {summary.stockout_within_horizon_count}",
            f"- SKUs needing reorder now: {summary.reorder_required_count}",
            f"- Total suggested reorder quantity: {summary.total_suggested_reorder_qty}",
            f"- Avg confidence: {self._format_optional_metric(summary.avg_confidence, 3)}",
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
            "## Top Reorder/Stockout Signals",
        ]

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

        confidence_values = [row.confidence_score for row in explainability_rows if row.confidence_score is not None]
        summary = ForecastReportSummary(
            sku_count=len(explainability_rows),
            recommendations_count=len(explainability_rows),
            stockout_within_horizon_count=sum(1 for row in explainability_rows if row.predicted_stockout_date is not None),
            reorder_required_count=sum(1 for row in explainability_rows if row.suggested_qty > 0),
            total_suggested_reorder_qty=sum(row.suggested_qty for row in explainability_rows),
            avg_confidence=float(mean(confidence_values)) if confidence_values else None,
        )
        product_ids = [row.product_id for row in explainability_rows]
        mature_product_ids: list[int] = []
        for product_id in product_ids:
            history = self._load_sales_history_dense(product_id)
            stock_movements = self._load_stock_movements(product_id)
            censored_dates = estimate_censored_sales_dates(
                history[["date", "units"]],
                stock_movements=stock_movements,
            )
            if self._is_mature_history(history, censored_dates=censored_dates):
                mature_product_ids.append(product_id)
        mature_sku_criteria = self._mature_sku_criteria_text()

        evaluation_full = self._evaluate_forecast_quality(
            product_ids,
            evaluation_days=evaluation_days,
        )
        evaluation_mature = self._evaluate_forecast_quality(
            mature_product_ids,
            evaluation_days=evaluation_days,
        )
        markdown_report = self._render_markdown_report(
            run,
            summary,
            evaluation_full,
            evaluation_mature,
            mature_sku_criteria,
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
            mature_sku_criteria=mature_sku_criteria,
            evaluation=evaluation_full,
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

    def get_item_forecast_detail(self, product_id: int) -> ItemForecastDetail:
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

        history_dense = self._load_sales_history_dense(product.id).tail(30)
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
