from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class LowStockRow(BaseModel):
    product_id: int
    sku: str
    name: str
    on_hand_qty: int
    reorder_threshold: int


class SalesTrendPoint(BaseModel):
    date: date
    total_sales: Decimal
    transactions: int


class DashboardKpis(BaseModel):
    sku_count: int
    low_stock_count: int
    today_sales: Decimal


class ScraperSourceQualityRow(BaseModel):
    source_id: int
    source_name: str
    mode: str
    enabled: bool
    snapshots_24h: int
    matched_skus_24h: int
    coverage_pct_24h: float
    effective_coverage_pct_24h: float | None = None
    latest_scraped_at: datetime | None
    minutes_since_latest: int | None
    stale: bool
    degraded: bool = False
    degradation_reason: str | None = None


class StockoutPredictionRow(BaseModel):
    product_id: int
    sku: str
    name: str
    predicted_stockout_date: date | None
    suggested_qty: int


class ForecastReportSummary(BaseModel):
    sku_count: int
    recommendations_count: int
    stockout_within_horizon_count: int
    reorder_required_count: int
    total_suggested_reorder_qty: int
    avg_confidence: float | None
    mature_sku_count: int | None = None
    non_mature_sku_count: int | None = None
    high_confidence_count: int | None = None
    high_confidence_mature_count: int | None = None
    high_confidence_non_mature_count: int | None = None


class ForecastEvaluationMetrics(BaseModel):
    evaluation_days: int
    evaluated_skus: int
    model_mae: float | None
    model_mape_pct: float | None
    model_wmape_pct: float | None = None
    baseline_mae: float | None
    baseline_mape_pct: float | None
    baseline_wmape_pct: float | None = None
    mae_improvement_pct: float | None = None
    wmape_improvement_pct: float | None = None
    mae_diff_ci95_low: float | None = None
    mae_diff_ci95_high: float | None = None
    wmape_diff_ci95_low: float | None = None
    wmape_diff_ci95_high: float | None = None
    sign_test_p_value: float | None = None
    better_than_baseline_skus: int = 0
    compared_skus: int = 0


class ForecastExplainabilityRow(BaseModel):
    product_id: int
    sku: str
    name: str
    on_hand_qty: int
    lead_time_days: int
    safety_stock: int
    predicted_30d_units: float
    avg_daily_units: float
    predicted_stockout_date: date | None
    reorder_point: int
    suggested_qty: int
    confidence_score: float | None
    data_tier: str | None = None
    explanation: str


class ForecastReportResponse(BaseModel):
    run_id: int
    run_at: datetime
    horizon_days: int
    model_version: str
    summary: ForecastReportSummary
    evaluation_full: ForecastEvaluationMetrics
    evaluation_mature: ForecastEvaluationMetrics
    evaluation_non_mature: ForecastEvaluationMetrics | None = None
    mature_sku_criteria: str
    evaluation: ForecastEvaluationMetrics
    qa_summary: str | None = None
    qa_report: str | None = None
    markdown_report: str
    explainability_rows: list[ForecastExplainabilityRow]


class ForecastRunComparisonRun(BaseModel):
    run_id: int
    run_at: datetime
    horizon_days: int
    model_version: str


class ForecastRunComparisonWindow(BaseModel):
    comparable_skus: int
    comparable_points: int
    actuals_start: date | None = None
    actuals_end: date | None = None


class ForecastRunComparisonMetrics(BaseModel):
    mae: float | None = None
    mape_pct: float | None = None
    wmape_pct: float | None = None
    avg_confidence: float | None = None
    stockout_within_horizon_count: int
    reorder_required_count: int
    total_suggested_reorder_qty: int


class ForecastRunComparisonDelta(BaseModel):
    mae: float | None = None
    mape_pct: float | None = None
    wmape_pct: float | None = None
    avg_confidence: float | None = None
    stockout_within_horizon_count: int
    reorder_required_count: int
    total_suggested_reorder_qty: int


class ForecastRunComparisonSkuRow(BaseModel):
    product_id: int
    sku: str
    name: str
    baseline_predicted_units_total: float | None = None
    candidate_predicted_units_total: float | None = None
    predicted_units_total_delta: float | None = None
    baseline_suggested_qty: int
    candidate_suggested_qty: int
    suggested_qty_delta: int
    baseline_confidence_score: float | None = None
    candidate_confidence_score: float | None = None
    confidence_score_delta: float | None = None
    baseline_predicted_stockout_date: date | None = None
    candidate_predicted_stockout_date: date | None = None


class ForecastRunValidationSnapshot(BaseModel):
    method: str
    evaluated_skus: int
    skipped_skus: int = 0
    model_wmape_pct: float | None = None
    baseline_wmape_pct: float | None = None
    wmape_improvement_pct: float | None = None
    raw_candidate_wmape_pct: float | None = None
    raw_candidate_wmape_improvement_pct: float | None = None
    total_windows_evaluated: int = 0
    model_win_count: int = 0
    model_win_rate_pct: float | None = None
    selected_strategy_fallback_count: int = 0
    selected_strategy_fallback_rate_pct: float | None = None
    mature_evaluated_skus: int = 0
    mature_raw_candidate_win_count: int = 0
    mature_raw_candidate_win_rate_pct: float | None = None


class ForecastRunValidationDelta(BaseModel):
    evaluated_skus: int = 0
    skipped_skus: int = 0
    model_wmape_pct: float | None = None
    baseline_wmape_pct: float | None = None
    wmape_improvement_pct: float | None = None
    raw_candidate_wmape_pct: float | None = None
    raw_candidate_wmape_improvement_pct: float | None = None
    total_windows_evaluated: int = 0
    model_win_count: int = 0
    model_win_rate_pct: float | None = None
    selected_strategy_fallback_count: int = 0
    selected_strategy_fallback_rate_pct: float | None = None
    mature_evaluated_skus: int = 0
    mature_raw_candidate_win_count: int = 0
    mature_raw_candidate_win_rate_pct: float | None = None


class ForecastRunValidationSkuRow(BaseModel):
    product_id: int | None = None
    sku: str
    baseline_data_tier: str | None = None
    candidate_data_tier: str | None = None
    baseline_quality_status: str | None = None
    candidate_quality_status: str | None = None
    baseline_selected_strategy_action: str | None = None
    candidate_selected_strategy_action: str | None = None
    baseline_fallback_reason: str | None = None
    candidate_fallback_reason: str | None = None
    baseline_selected_model_name: str | None = None
    candidate_selected_model_name: str | None = None
    baseline_raw_candidate_model_name: str | None = None
    candidate_raw_candidate_model_name: str | None = None
    baseline_selected_wmape_pct: float | None = None
    candidate_selected_wmape_pct: float | None = None
    selected_wmape_delta: float | None = None
    baseline_raw_candidate_wmape_pct: float | None = None
    candidate_raw_candidate_wmape_pct: float | None = None
    raw_candidate_wmape_delta: float | None = None
    baseline_baseline_wmape_pct: float | None = None
    candidate_baseline_wmape_pct: float | None = None
    baseline_raw_candidate_gap_vs_baseline_pct: float | None = None
    candidate_raw_candidate_gap_vs_baseline_pct: float | None = None
    raw_candidate_gap_vs_baseline_delta: float | None = None


class ForecastRunValidationComparison(BaseModel):
    verdict: str
    baseline: ForecastRunValidationSnapshot | None = None
    candidate: ForecastRunValidationSnapshot | None = None
    delta: ForecastRunValidationDelta | None = None


class ForecastRunComparisonResponse(BaseModel):
    baseline_run: ForecastRunComparisonRun
    candidate_run: ForecastRunComparisonRun
    verdict: str
    metrics: ForecastRunComparisonWindow
    baseline: ForecastRunComparisonMetrics
    candidate: ForecastRunComparisonMetrics
    delta: ForecastRunComparisonDelta
    validation: ForecastRunValidationComparison | None = None
    validation_sku_rows: list[ForecastRunValidationSkuRow] = []
    sku_rows: list[ForecastRunComparisonSkuRow]


class ItemDemandPoint(BaseModel):
    date: date
    units: float
    kind: str


class ItemPriceBenchmark(BaseModel):
    source_name: str
    price: Decimal


class ItemPriceAnalysis(BaseModel):
    store_price: Decimal
    market_avg_price: Decimal | None
    difference_pct: Decimal | None
    suggested_price: Decimal | None
    competitor_benchmarks: list[ItemPriceBenchmark]


class ItemForecastDetail(BaseModel):
    product_id: int
    sku: str
    name: str
    forecast_horizon_days: int
    predicted_per_month: float
    in_stock: int
    reorder_qty: int
    confidence_pct: float | None
    predicted_stockout_date: date | None
    days_until_stockout: int | None
    when_to_buy_message: str
    demand_points: list[ItemDemandPoint]
    price_analysis: ItemPriceAnalysis
