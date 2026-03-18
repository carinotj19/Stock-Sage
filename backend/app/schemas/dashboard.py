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
    explanation: str


class ForecastReportResponse(BaseModel):
    run_id: int
    run_at: datetime
    horizon_days: int
    model_version: str
    summary: ForecastReportSummary
    evaluation_full: ForecastEvaluationMetrics
    evaluation_mature: ForecastEvaluationMetrics
    mature_sku_criteria: str
    evaluation: ForecastEvaluationMetrics
    markdown_report: str
    explainability_rows: list[ForecastExplainabilityRow]


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
