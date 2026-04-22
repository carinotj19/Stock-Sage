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

export type SaleTransactionRow = {
  transaction_id: number;
  item_id: number;
  receipt_no: string;
  sold_at: string;
  product_id: number;
  sku: string;
  product_name: string;
  qty: number;
  unit_sell_price: string;
  line_total: string;
  total_amount: string;
  payment_method: string | null;
  ordered_by_username?: string | null;
};

export type SaleTransactionPage = {
  items: SaleTransactionRow[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
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

export type UserRole = "super_admin" | "admin" | "staff";

export type AccountRow = {
  id: number;
  username: string;
  display_name: string;
  email: string | null;
  role: UserRole;
  status: "active" | "inactive";
  created_at: string;
  last_login_at: string | null;
};

export type SystemSettings = {
  auth_enabled: boolean;
  configured: boolean;
  active_accounts: number;
  super_admin_accounts?: number;
  admin_accounts: number;
  staff_accounts: number;
  session_ttl_seconds: number;
};

export type ManualScrapeRunResult = {
  inserted_rows: number;
  ran_at: string;
  message: string;
};

export type ManualScrapeJobStatus = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress_pct: number;
  current_source: string | null;
  inserted_rows: number;
  total_sources: number;
  completed_sources: number;
  started_at: string;
  finished_at: string | null;
  message: string;
  error: string | null;
  logs: string[];
};

export type AuditLogRow = {
  id: number;
  actor_username: string;
  action: string;
  target_type: string;
  target_id: number | null;
  message: string;
  created_at: string;
};
