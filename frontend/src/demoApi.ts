import type {
  ItemForecastDetail,
  LowStockRow,
  PriceComparisonRow,
  ProductRow,
  SaleTransactionPage,
  SaleTransactionRow,
  ScraperSourceQualityRow,
  SalesTrendPoint,
  StockoutRow
} from "./types";

type AuthStatus = {
  authenticated: boolean;
  configured: boolean;
  username: string | null;
  display_name: string | null;
  role: "super_admin" | "admin" | "staff" | null;
};

const now = new Date();
const isoDate = (offsetDays: number) => {
  const date = new Date(now);
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
};
const isoDateTime = (offsetDays: number, hour = 10) => `${isoDate(offsetDays)}T${String(hour).padStart(2, "0")}:30:00+08:00`;

const products: ProductRow[] = [
  {
    id: 1,
    sku: "GPU-RTX4070S",
    name: "GeForce RTX 4070 SUPER 12GB",
    category: "GPU",
    supplier_id: 1,
    cost_price: "33250.00",
    sell_price: "37995.00",
    reorder_min_qty: 3,
    reorder_multiple: 2,
    safety_stock: 2,
    active: true,
    on_hand_qty: 7,
    created_at: isoDateTime(-90),
    updated_at: isoDateTime(-1)
  },
  {
    id: 2,
    sku: "SSD-NVME-1TB",
    name: "NVMe Gen4 SSD 1TB",
    category: "SSD",
    supplier_id: 2,
    cost_price: "2650.00",
    sell_price: "3295.00",
    reorder_min_qty: 8,
    reorder_multiple: 4,
    safety_stock: 5,
    active: true,
    on_hand_qty: 4,
    created_at: isoDateTime(-120),
    updated_at: isoDateTime(-2)
  },
  {
    id: 3,
    sku: "RAM-DDR5-32",
    name: "DDR5 32GB 6000MHz Kit",
    category: "RAM",
    supplier_id: 2,
    cost_price: "4250.00",
    sell_price: "4995.00",
    reorder_min_qty: 6,
    reorder_multiple: 2,
    safety_stock: 4,
    active: true,
    on_hand_qty: 3,
    created_at: isoDateTime(-110),
    updated_at: isoDateTime(-1)
  },
  {
    id: 4,
    sku: "CPU-R7-9700X",
    name: "Ryzen 7 9700X",
    category: "CPU",
    supplier_id: 3,
    cost_price: "18200.00",
    sell_price: "20995.00",
    reorder_min_qty: 4,
    reorder_multiple: 2,
    safety_stock: 2,
    active: true,
    on_hand_qty: 9,
    created_at: isoDateTime(-80),
    updated_at: isoDateTime(-3)
  },
  {
    id: 5,
    sku: "MB-B650-WIFI",
    name: "B650 WiFi ATX Motherboard",
    category: "Motherboard",
    supplier_id: 3,
    cost_price: "9450.00",
    sell_price: "10995.00",
    reorder_min_qty: 4,
    reorder_multiple: 2,
    safety_stock: 2,
    active: true,
    on_hand_qty: 5,
    created_at: isoDateTime(-75),
    updated_at: isoDateTime(-2)
  },
  {
    id: 6,
    sku: "PSU-850-GOLD",
    name: "850W 80+ Gold Modular PSU",
    category: "PSU",
    supplier_id: 4,
    cost_price: "5150.00",
    sell_price: "6195.00",
    reorder_min_qty: 5,
    reorder_multiple: 2,
    safety_stock: 3,
    active: true,
    on_hand_qty: 2,
    created_at: isoDateTime(-70),
    updated_at: isoDateTime(-1)
  },
  {
    id: 7,
    sku: "CASE-AIRFLOW-X",
    name: "Airflow Mid Tower Case",
    category: "Case",
    supplier_id: 4,
    cost_price: "2850.00",
    sell_price: "3495.00",
    reorder_min_qty: 5,
    reorder_multiple: 2,
    safety_stock: 3,
    active: true,
    on_hand_qty: 11,
    created_at: isoDateTime(-65),
    updated_at: isoDateTime(-5)
  },
  {
    id: 8,
    sku: "COOL-AIO-240",
    name: "240mm ARGB AIO Cooler",
    category: "Cooler",
    supplier_id: 5,
    cost_price: "3350.00",
    sell_price: "4195.00",
    reorder_min_qty: 4,
    reorder_multiple: 2,
    safety_stock: 2,
    active: true,
    on_hand_qty: 6,
    created_at: isoDateTime(-60),
    updated_at: isoDateTime(-2)
  }
];

const lowStock: LowStockRow[] = [
  { product_id: 2, sku: "SSD-NVME-1TB", name: "NVMe Gen4 SSD 1TB", on_hand_qty: 4, reorder_threshold: 8 },
  { product_id: 3, sku: "RAM-DDR5-32", name: "DDR5 32GB 6000MHz Kit", on_hand_qty: 3, reorder_threshold: 6 },
  { product_id: 6, sku: "PSU-850-GOLD", name: "850W 80+ Gold Modular PSU", on_hand_qty: 2, reorder_threshold: 5 }
];

const stockouts: StockoutRow[] = [
  { product_id: 2, sku: "SSD-NVME-1TB", name: "NVMe Gen4 SSD 1TB", predicted_stockout_date: isoDate(4), suggested_qty: 16 },
  { product_id: 3, sku: "RAM-DDR5-32", name: "DDR5 32GB 6000MHz Kit", predicted_stockout_date: isoDate(6), suggested_qty: 12 },
  { product_id: 6, sku: "PSU-850-GOLD", name: "850W 80+ Gold Modular PSU", predicted_stockout_date: isoDate(3), suggested_qty: 10 }
];

const priceComparisons: PriceComparisonRow[] = [
  { product_id: 1, sku: "GPU-RTX4070S", name: "GeForce RTX 4070 SUPER 12GB", store_price: "37995.00", cheapest_competitor_price: "38450.00", price_gap: "-455.00", price_gap_pct: "-1.18", is_above_cheapest: false },
  { product_id: 2, sku: "SSD-NVME-1TB", name: "NVMe Gen4 SSD 1TB", store_price: "3295.00", cheapest_competitor_price: "3199.00", price_gap: "96.00", price_gap_pct: "3.00", is_above_cheapest: true },
  { product_id: 3, sku: "RAM-DDR5-32", name: "DDR5 32GB 6000MHz Kit", store_price: "4995.00", cheapest_competitor_price: "5140.00", price_gap: "-145.00", price_gap_pct: "-2.82", is_above_cheapest: false },
  { product_id: 4, sku: "CPU-R7-9700X", name: "Ryzen 7 9700X", store_price: "20995.00", cheapest_competitor_price: "20750.00", price_gap: "245.00", price_gap_pct: "1.18", is_above_cheapest: true },
  { product_id: 5, sku: "MB-B650-WIFI", name: "B650 WiFi ATX Motherboard", store_price: "10995.00", cheapest_competitor_price: "11250.00", price_gap: "-255.00", price_gap_pct: "-2.27", is_above_cheapest: false }
];

const salesTrend: SalesTrendPoint[] = Array.from({ length: 30 }, (_, index) => {
  const offset = index - 29;
  const wave = [14850, 19200, 17350, 23100, 20650, 25750, 21900][index % 7];
  return {
    date: isoDate(offset),
    total_sales: String(wave + (index % 5) * 1750),
    transactions: 3 + (index % 6)
  };
});

const transactions: SaleTransactionRow[] = [
  { transaction_id: 1006, item_id: 1006, receipt_no: "SS-2026-1042", sold_at: isoDateTime(0, 11), product_id: 2, sku: "SSD-NVME-1TB", product_name: "NVMe Gen4 SSD 1TB", qty: 2, unit_sell_price: "3295.00", line_total: "6590.00", total_amount: "6590.00", payment_method: "card", ordered_by_username: "Demo Staff" },
  { transaction_id: 1005, item_id: 1005, receipt_no: "SS-2026-1041", sold_at: isoDateTime(-1, 16), product_id: 1, sku: "GPU-RTX4070S", product_name: "GeForce RTX 4070 SUPER 12GB", qty: 1, unit_sell_price: "37995.00", line_total: "37995.00", total_amount: "37995.00", payment_method: "online", ordered_by_username: "Demo Staff" },
  { transaction_id: 1004, item_id: 1004, receipt_no: "SS-2026-1040", sold_at: isoDateTime(-2, 13), product_id: 3, sku: "RAM-DDR5-32", product_name: "DDR5 32GB 6000MHz Kit", qty: 2, unit_sell_price: "4995.00", line_total: "9990.00", total_amount: "9990.00", payment_method: "cash", ordered_by_username: "Demo Staff" },
  { transaction_id: 1003, item_id: 1003, receipt_no: "SS-2026-1039", sold_at: isoDateTime(-3, 17), product_id: 4, sku: "CPU-R7-9700X", product_name: "Ryzen 7 9700X", qty: 1, unit_sell_price: "20995.00", line_total: "20995.00", total_amount: "20995.00", payment_method: "card", ordered_by_username: "Demo Staff" },
  { transaction_id: 1002, item_id: 1002, receipt_no: "SS-2026-1038", sold_at: isoDateTime(-4, 15), product_id: 7, sku: "CASE-AIRFLOW-X", product_name: "Airflow Mid Tower Case", qty: 1, unit_sell_price: "3495.00", line_total: "3495.00", total_amount: "3495.00", payment_method: "cash", ordered_by_username: "Demo Staff" },
  { transaction_id: 1001, item_id: 1001, receipt_no: "SS-2026-1037", sold_at: isoDateTime(-5, 12), product_id: 8, sku: "COOL-AIO-240", product_name: "240mm ARGB AIO Cooler", qty: 1, unit_sell_price: "4195.00", line_total: "4195.00", total_amount: "4195.00", payment_method: "online", ordered_by_username: "Demo Staff" }
];

const sourceQuality: ScraperSourceQualityRow[] = [
  { source_id: 1, source_name: "Retailer Alpha", mode: "html", enabled: true, snapshots_24h: 38, matched_skus_24h: 8, coverage_pct_24h: 100, effective_coverage_pct_24h: 100, latest_scraped_at: isoDateTime(0, 12), minutes_since_latest: 18, stale: false, degraded: false, degradation_reason: null },
  { source_id: 2, source_name: "Retailer Beta", mode: "browser", enabled: true, snapshots_24h: 31, matched_skus_24h: 7, coverage_pct_24h: 87.5, effective_coverage_pct_24h: 87.5, latest_scraped_at: isoDateTime(0, 11), minutes_since_latest: 54, stale: false, degraded: false, degradation_reason: null },
  { source_id: 3, source_name: "Retailer Gamma", mode: "html", enabled: true, snapshots_24h: 22, matched_skus_24h: 6, coverage_pct_24h: 75, effective_coverage_pct_24h: 75, latest_scraped_at: isoDateTime(-1, 17), minutes_since_latest: 190, stale: true, degraded: true, degradation_reason: "Latest scrape is older than the freshness target." }
];

const buildForecast = (productId: number): ItemForecastDetail => {
  const product = products.find((item) => item.id === productId) ?? products[0];
  const history = Array.from({ length: 30 }, (_, index) => ({
    date: isoDate(index - 29),
    units: Math.max(0, 1 + ((index * product.id) % 5)),
    kind: "history" as const
  }));
  const forecast = Array.from({ length: 14 }, (_, index) => ({
    date: isoDate(index + 1),
    units: 2 + ((index + product.id) % 4),
    kind: "forecast" as const
  }));
  const competitor = priceComparisons.find((row) => row.product_id === product.id);

  return {
    product_id: product.id,
    sku: product.sku,
    name: product.name,
    forecast_horizon_days: 30,
    predicted_per_month: 48 + product.id * 4,
    in_stock: product.on_hand_qty,
    reorder_qty: product.on_hand_qty <= product.reorder_min_qty ? product.reorder_multiple * 4 : 0,
    confidence_pct: 86.4,
    predicted_stockout_date: product.on_hand_qty <= product.reorder_min_qty ? isoDate(4 + product.id) : null,
    days_until_stockout: product.on_hand_qty <= product.reorder_min_qty ? 4 + product.id : null,
    when_to_buy_message:
      product.on_hand_qty <= product.reorder_min_qty
        ? "Reorder soon based on current stock and forecast demand."
        : "Current stock is sufficient for the near-term forecast window.",
    demand_points: [...history, ...forecast],
    price_analysis: {
      store_price: product.sell_price,
      market_avg_price: competitor?.cheapest_competitor_price ?? product.sell_price,
      difference_pct: competitor?.price_gap_pct ?? "0.00",
      suggested_price: competitor?.cheapest_competitor_price ?? product.sell_price,
      competitor_benchmarks: [
        { source_name: "Retailer Alpha", price: competitor?.cheapest_competitor_price ?? product.sell_price },
        { source_name: "Retailer Beta", price: String(Math.round(Number(product.sell_price) * 1.015)) }
      ]
    }
  };
};

const buildSalesPage = (path: string): SaleTransactionPage => {
  const url = new URL(path, "https://demo.stock-sage.local");
  const page = Math.max(1, Number(url.searchParams.get("page") ?? "1"));
  const pageSize = Math.max(1, Number(url.searchParams.get("page_size") ?? "50"));
  const search = (url.searchParams.get("search") ?? "").trim().toLowerCase();
  const dateFrom = url.searchParams.get("date_from");
  const dateTo = url.searchParams.get("date_to");
  const sort = url.searchParams.get("sort") === "asc" ? "asc" : "desc";

  let rows = transactions.filter((row) => {
    const soldDate = row.sold_at.slice(0, 10);
    if (dateFrom && soldDate < dateFrom) return false;
    if (dateTo && soldDate > dateTo) return false;
    if (!search) return true;
    return [row.receipt_no, row.sku, row.product_name, row.ordered_by_username ?? "", row.payment_method ?? ""]
      .join(" ")
      .toLowerCase()
      .includes(search);
  });

  rows = [...rows].sort((a, b) => (sort === "asc" ? a.sold_at.localeCompare(b.sold_at) : b.sold_at.localeCompare(a.sold_at)));
  const total = rows.length;
  const start = (page - 1) * pageSize;

  return {
    items: rows.slice(start, start + pageSize),
    total,
    page,
    page_size: pageSize,
    total_pages: Math.max(1, Math.ceil(total / pageSize))
  };
};

export const demoRequestJson = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const method = (init?.method ?? "GET").toUpperCase();

  if (path === "/auth/me") {
    return {
      authenticated: true,
      configured: true,
      username: "demo",
      display_name: "Demo Viewer",
      role: "staff"
    } as T & AuthStatus;
  }

  if (method !== "GET") {
    throw new Error("Public demo is read-only. Clone the repository to try write operations locally.");
  }

  if (path === "/products") return products as T;
  if (path === "/dashboard/low-stock") return lowStock as T;
  if (path === "/dashboard/stockout-dates") return stockouts as T;
  if (path === "/prices/compare") return priceComparisons as T;
  if (path.startsWith("/dashboard/sales-trend")) return salesTrend as T;
  if (path.startsWith("/dashboard/scraper-source-quality")) return sourceQuality as T;
  if (path.startsWith("/sales?")) return buildSalesPage(path) as T;

  const forecastMatch = path.match(/^\/dashboard\/item-forecast\/(\d+)/);
  if (forecastMatch) return buildForecast(Number(forecastMatch[1])) as T;

  throw new Error(`Demo data is not available for ${path}`);
};
