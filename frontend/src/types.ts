export type LowStockRow = {
  product_id: number;
  sku: string;
  name: string;
  on_hand_qty: number;
  reorder_threshold: number;
};

export type StockoutRow = {
  product_id: number;
  sku: string;
  name: string;
  predicted_stockout_date: string | null;
  suggested_qty: number;
};

export type PriceComparisonRow = {
  product_id: number;
  sku: string;
  name: string;
  store_price: string;
  cheapest_competitor_price: string | null;
  price_gap: string | null;
  price_gap_pct: string | null;
  is_above_cheapest: boolean;
};

export type SalesTrendPoint = {
  date: string;
  total_sales: string;
  transactions: number;
};

export type ScraperSourceQualityRow = {
  source_id: number;
  source_name: string;
  mode: string;
  enabled: boolean;
  snapshots_24h: number;
  matched_skus_24h: number;
  coverage_pct_24h: number;
  effective_coverage_pct_24h?: number | null;
  latest_scraped_at: string | null;
  minutes_since_latest: number | null;
  stale: boolean;
  degraded?: boolean;
  degradation_reason?: string | null;
};

export type ProductRow = {
  id: number;
  sku: string;
  name: string;
  category: string | null;
  supplier_id: number | null;
  cost_price: string;
  sell_price: string;
  reorder_min_qty: number;
  reorder_multiple: number;
  safety_stock: number;
  active: boolean;
  on_hand_qty: number;
  created_at: string;
  updated_at: string;
};

export type ForecastReportSummary = {
  sku_count: number;
  recommendations_count: number;
  stockout_within_horizon_count: number;
  reorder_required_count: number;
  total_suggested_reorder_qty: number;
  avg_confidence: number | null;
};

export type ForecastEvaluationMetrics = {
  evaluation_days: number;
  evaluated_skus: number;
  model_mae: number | null;
  model_mape_pct: number | null;
  model_wmape_pct: number | null;
  baseline_mae: number | null;
  baseline_mape_pct: number | null;
  baseline_wmape_pct: number | null;
  mae_improvement_pct: number | null;
  wmape_improvement_pct: number | null;
  mae_diff_ci95_low: number | null;
  mae_diff_ci95_high: number | null;
  wmape_diff_ci95_low: number | null;
  wmape_diff_ci95_high: number | null;
  sign_test_p_value: number | null;
  better_than_baseline_skus: number;
  compared_skus: number;
};

export type ForecastExplainabilityRow = {
  product_id: number;
  sku: string;
  name: string;
  on_hand_qty: number;
  lead_time_days: number;
  safety_stock: number;
  predicted_30d_units: number;
  avg_daily_units: number;
  predicted_stockout_date: string | null;
  reorder_point: number;
  suggested_qty: number;
  confidence_score: number | null;
  explanation: string;
};

export type ForecastReportResponse = {
  run_id: number;
  run_at: string;
  horizon_days: number;
  model_version: string;
  summary: ForecastReportSummary;
  evaluation_full: ForecastEvaluationMetrics;
  evaluation_mature: ForecastEvaluationMetrics;
  mature_sku_criteria: string;
  evaluation: ForecastEvaluationMetrics;
  markdown_report: string;
  explainability_rows: ForecastExplainabilityRow[];
};

export type ItemDemandPoint = {
  date: string;
  units: number;
  kind: "history" | "forecast";
};

export type ItemPriceBenchmark = {
  source_name: string;
  price: string;
};

export type ItemPriceAnalysis = {
  store_price: string;
  market_avg_price: string | null;
  difference_pct: string | null;
  suggested_price: string | null;
  competitor_benchmarks: ItemPriceBenchmark[];
};

export type ItemForecastDetail = {
  product_id: number;
  sku: string;
  name: string;
  forecast_horizon_days: number;
  predicted_per_month: number;
  in_stock: number;
  reorder_qty: number;
  confidence_pct: number | null;
  predicted_stockout_date: string | null;
  days_until_stockout: number | null;
  when_to_buy_message: string;
  demand_points: ItemDemandPoint[];
  price_analysis: ItemPriceAnalysis;
};
