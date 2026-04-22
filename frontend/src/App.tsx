import { FormEvent, useEffect, useMemo, useState } from "react";
import { AdminLogin } from "./components/AdminLogin";
import { ForecastItemModal } from "./components/ForecastItemModal";
import { InventoryProductsTable } from "./components/InventoryProductsTable";
import { LowStockTable } from "./components/LowStockTable";
import { PriceComparisonTable } from "./components/PriceComparisonTable";
import { SettingsPanel } from "./components/SettingsPanel";
import { SourceQualityPanel } from "./components/SourceQualityPanel";
import { StockoutCard } from "./components/StockoutCard";
import type {
  ItemForecastDetail,
  ManualScrapeJobStatus,
  ProductRow,
  LowStockRow,
  PriceComparisonRow,
  SaleTransactionPage,
  SaleTransactionRow,
  ScraperSourceQualityRow,
  SalesTrendPoint,
  StockoutRow,
  UserRole
} from "./types";
import "./styles.css";
import type { InventoryProductUpdatePayload } from "./components/InventoryProductsTable";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const PRODUCT_CATEGORY_OPTIONS = ["Case", "Cooler", "CPU", "GPU", "Motherboard", "PSU", "RAM", "SSD"];
const ITEM_FORECAST_HISTORY_DAYS = 365;
const TRANSACTION_PAGE_SIZE = 50;
const SCRAPE_JOB_POLL_INTERVAL_MS = 1000;

const isAdminRole = (role: UserRole | null) => role === "admin" || role === "super_admin";
const isScrapeJobRunning = (job: ManualScrapeJobStatus | null) => job?.status === "queued" || job?.status === "running";

type AuthStatus = {
  authenticated: boolean;
  configured: boolean;
  username: string | null;
  display_name: string | null;
  role: UserRole | null;
};

type AuthState =
  | { status: "checking" }
  | { status: "authenticated"; username: string; displayName: string; role: UserRole }
  | { status: "anonymous" };

const readApiError = async (response: Response) => {
  const body = await response.text();
  if (!body) return `${response.status} ${response.statusText}`;

  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    return body;
  }

  return body;
};

const requestJson = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const requestUrl = `${API_BASE_URL}${path}`;
  let response: Response;

  try {
    response = await fetch(requestUrl, { ...init, credentials: "include" });
  } catch (error) {
    throw new Error(
      `Cannot reach the API. Check that the backend is live and CORS allows this frontend. Original error: ${String(error)}`
    );
  }

  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return (await response.json()) as T;
};

const toDateOnlyTimestamp = (dateString: string) => new Date(`${dateString}T00:00:00`).getTime();

const App = () => {
  const formatPHP = (value: string) => {
    const numeric = Number(value);
    if (Number.isNaN(numeric)) return value;
    return new Intl.NumberFormat("en-PH", {
      style: "currency",
      currency: "PHP",
      minimumFractionDigits: 2
    }).format(numeric);
  };
  const formatPHPCompact = (value: number) =>
    new Intl.NumberFormat("en-PH", {
      style: "currency",
      currency: "PHP",
      maximumFractionDigits: 0
    }).format(value);
  const formatPHPWhole = (value: string | number) => {
    const numeric = Number(value);
    if (Number.isNaN(numeric)) return String(value);
    return formatPHPCompact(numeric);
  };
  const formatTransactionDate = (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    return new Intl.DateTimeFormat("en-US", {
      month: "numeric",
      day: "numeric",
      year: "numeric"
    }).format(date);
  };
  const formatTransactionDateTime = (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    return new Intl.DateTimeFormat("en-PH", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit"
    }).format(date);
  };

  const [activeTab, setActiveTab] = useState<"dashboard" | "inventory" | "transactions" | "settings">("dashboard");
  const [authState, setAuthState] = useState<AuthState>({ status: "checking" });
  const [loginError, setLoginError] = useState<string | null>(null);
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isScraping, setIsScraping] = useState<boolean>(false);
  const [scrapeJob, setScrapeJob] = useState<ManualScrapeJobStatus | null>(null);
  const [scrapeJobId, setScrapeJobId] = useState<string | null>(null);
  const [isScrapeConsoleOpen, setIsScrapeConsoleOpen] = useState<boolean>(false);

  const [lowStock, setLowStock] = useState<LowStockRow[]>([]);
  const [stockoutRows, setStockoutRows] = useState<StockoutRow[]>([]);
  const [priceRows, setPriceRows] = useState<PriceComparisonRow[]>([]);
  const [salesTrend, setSalesTrend] = useState<SalesTrendPoint[]>([]);
  const [transactionRows, setTransactionRows] = useState<SaleTransactionRow[]>([]);
  const [products, setProducts] = useState<ProductRow[]>([]);
  const [sourceQualityRows, setSourceQualityRows] = useState<ScraperSourceQualityRow[]>([]);
  const [selectedForecastProductId, setSelectedForecastProductId] = useState<number | null>(null);
  const [selectedForecastItem, setSelectedForecastItem] = useState<ItemForecastDetail | null>(null);
  const [isForecastModalLoading, setIsForecastModalLoading] = useState<boolean>(false);
  const [forecastModalError, setForecastModalError] = useState<string | null>(null);
  const [selectedTransactionItemId, setSelectedTransactionItemId] = useState<number | null>(null);
  const [transactionDateFilter, setTransactionDateFilter] = useState({
    from: "",
    to: ""
  });
  const [transactionDateSort, setTransactionDateSort] = useState<"asc" | "desc">("desc");
  const [transactionPage, setTransactionPage] = useState(1);
  const [transactionTotal, setTransactionTotal] = useState(0);
  const [transactionTotalPages, setTransactionTotalPages] = useState(1);
  const [isTransactionLoading, setIsTransactionLoading] = useState(false);

  const [newProduct, setNewProduct] = useState({
    sku: "",
    name: "",
    category: "",
    cost_price: "0.00",
    sell_price: "0.00",
    initial_stock: "0",
    reorder_min_qty: "1",
    reorder_multiple: "1",
    safety_stock: "0"
  });
  const [adjustStock, setAdjustStock] = useState({
    product_id: "",
    qty_delta: "",
    reason: "manual_adjustment"
  });
  const [newSale, setNewSale] = useState({
    product_id: "",
    qty: "1",
    ordered_by_username: "",
    payment_method: "cash"
  });
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);

  const todayString = new Date().toISOString().slice(0, 10);
  const lowStockCount = lowStock.length;
  const outOfStockCount = lowStock.filter((row) => row.on_hand_qty <= 0).length;
  const totalInventoryValue = products.reduce(
    (total, product) => total + product.on_hand_qty * Number(product.sell_price),
    0
  );
  const revenueToday = Number(salesTrend.find((point) => point.date === todayString)?.total_sales ?? 0);
  const selectedTransaction = useMemo(
    () =>
      selectedTransactionItemId === null
        ? null
        : transactionRows.find((transaction) => transaction.item_id === selectedTransactionItemId) ?? null,
    [selectedTransactionItemId, transactionRows]
  );
  const transactionPageCount = Math.max(1, transactionTotalPages);
  const normalizedTransactionPage = Math.min(transactionPage, transactionPageCount);
  const transactionRangeStart = transactionTotal === 0 ? 0 : (normalizedTransactionPage - 1) * TRANSACTION_PAGE_SIZE + 1;
  const transactionRangeEnd = Math.min(normalizedTransactionPage * TRANSACTION_PAGE_SIZE, transactionTotal);
  const upcomingStockoutsCount = stockoutRows.filter((row) => {
    if (!row.predicted_stockout_date) return false;
    const daysLeft = Math.ceil((toDateOnlyTimestamp(row.predicted_stockout_date) - toDateOnlyTimestamp(todayString)) / 86400000);
    return daysLeft >= 0 && daysLeft <= 5;
  }).length;
  const lastUpdatedLabel = (() => {
    if (!lastUpdatedAt) return "Last updated: --";
    const minutes = Math.floor((Date.now() - lastUpdatedAt.getTime()) / 60000);
    if (minutes <= 0) return "Last updated: just now";
    if (minutes === 1) return "Last updated: 1 minute ago";
    if (minutes < 60) return `Last updated: ${minutes} minutes ago`;
    return `Last updated: ${new Intl.DateTimeFormat("en-PH", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit"
    }).format(lastUpdatedAt)}`;
  })();

  const clearDashboardData = () => {
    setLowStock([]);
    setStockoutRows([]);
    setPriceRows([]);
    setSalesTrend([]);
    setTransactionRows([]);
    setTransactionTotal(0);
    setTransactionTotalPages(1);
    setTransactionPage(1);
    setProducts([]);
    setSourceQualityRows([]);
    setSelectedForecastProductId(null);
    setSelectedForecastItem(null);
    setSelectedTransactionItemId(null);
    setApiError(null);
    setActionMessage(null);
    setLastUpdatedAt(null);
    setIsLoading(false);
  };

  const checkAuth = async () => {
    setLoginError(null);
    try {
      const status = await requestJson<AuthStatus>("/auth/me");
      if (status.authenticated) {
        const username = status.username ?? "admin";
        setAuthState({
          status: "authenticated",
          username,
          displayName: status.display_name ?? username,
          role: status.role ?? "admin"
        });
        return;
      }

      setAuthState({ status: "anonymous" });
      if (!status.configured) {
        setLoginError("Admin login is not configured. Set ADMIN_SESSION_SECRET and create an admin user from the backend CLI.");
      }
    } catch (error) {
      setAuthState({ status: "anonymous" });
      setLoginError(`Cannot check admin session: ${String(error)}`);
    }
  };

  const onAdminLogin = async (username: string, password: string) => {
    setIsLoggingIn(true);
    setLoginError(null);
    try {
      const status = await requestJson<AuthStatus>("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      if (!status.authenticated) {
        throw new Error("Admin login failed.");
      }
      const authenticatedUsername = status.username ?? username;
      setAuthState({
        status: "authenticated",
        username: authenticatedUsername,
        displayName: status.display_name ?? authenticatedUsername,
        role: status.role ?? "admin"
      });
      setActiveTab("dashboard");
    } catch (error) {
      setLoginError(`Sign in failed: ${String(error)}`);
    } finally {
      setIsLoggingIn(false);
    }
  };

  const onLogout = async () => {
    try {
      await requestJson<AuthStatus>("/auth/logout", { method: "POST" });
    } catch {
      // Local state is cleared even if the session already expired server-side.
    }
    clearDashboardData();
    setActiveTab("dashboard");
    setAuthState({ status: "anonymous" });
  };

  const applyLoadedProducts = (loadedProducts: ProductRow[]) => {
    setProducts(loadedProducts);
    if (!adjustStock.product_id && loadedProducts.length > 0) {
      setAdjustStock((prev) => ({ ...prev, product_id: String(loadedProducts[0].id) }));
    }
    if (!newSale.product_id && loadedProducts.length > 0) {
      setNewSale((prev) => ({ ...prev, product_id: String(loadedProducts[0].id) }));
    }
  };

  const buildSalesPath = ({
    page = transactionPage,
    dateFilter = transactionDateFilter,
    sort = transactionDateSort
  }: {
    page?: number;
    dateFilter?: typeof transactionDateFilter;
    sort?: typeof transactionDateSort;
  } = {}) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(TRANSACTION_PAGE_SIZE),
      sort
    });
    if (dateFilter.from) params.set("date_from", dateFilter.from);
    if (dateFilter.to) params.set("date_to", dateFilter.to);
    return `/sales?${params.toString()}`;
  };

  const applyTransactionPage = (pageData: SaleTransactionPage) => {
    setTransactionRows(Array.isArray(pageData.items) ? pageData.items : []);
    setTransactionPage(pageData.page ?? 1);
    setTransactionTotal(pageData.total ?? 0);
    setTransactionTotalPages(pageData.total_pages ?? 1);
  };

  const loadTransactionPage = async ({
    page = transactionPage,
    dateFilter = transactionDateFilter,
    sort = transactionDateSort
  }: {
    page?: number;
    dateFilter?: typeof transactionDateFilter;
    sort?: typeof transactionDateSort;
  } = {}) => {
    setIsTransactionLoading(true);
    try {
      const pageData = await requestJson<SaleTransactionPage>(buildSalesPath({ page, dateFilter, sort }));
      applyTransactionPage(pageData);
      setApiError(null);
      return true;
    } catch (error) {
      setApiError(`Cannot load transactions: ${String(error)}`);
      return false;
    } finally {
      setIsTransactionLoading(false);
    }
  };

  const loadData = async () => {
    setIsLoading(true);
    setApiError(null);
    setActionMessage(null);

    const results = await Promise.allSettled([
      requestJson<LowStockRow[]>("/dashboard/low-stock"),
      requestJson<StockoutRow[]>("/dashboard/stockout-dates"),
      requestJson<PriceComparisonRow[]>("/prices/compare"),
      requestJson<SalesTrendPoint[]>("/dashboard/sales-trend?days=30"),
      requestJson<ProductRow[]>("/products"),
      requestJson<ScraperSourceQualityRow[]>("/dashboard/scraper-source-quality?window_hours=24"),
      requestJson<SaleTransactionPage>(buildSalesPath())
    ]);

    const [lowStockResult, stockoutResult, priceResult, salesResult, productResult, sourceQualityResult, transactionResult] = results;

    if (lowStockResult.status === "fulfilled") setLowStock(lowStockResult.value);
    if (stockoutResult.status === "fulfilled") setStockoutRows(stockoutResult.value);
    if (priceResult.status === "fulfilled") setPriceRows(priceResult.value);
    if (salesResult.status === "fulfilled") setSalesTrend(salesResult.value);
    if (productResult.status === "fulfilled") {
      applyLoadedProducts(productResult.value);
    }
    if (sourceQualityResult.status === "fulfilled") setSourceQualityRows(sourceQualityResult.value);
    if (transactionResult.status === "fulfilled") applyTransactionPage(transactionResult.value);

    const firstError = results.find((item) => item.status === "rejected");
    if (firstError && firstError.status === "rejected") {
      setApiError(
        "Cannot load latest data. Ensure backend is running and CORS allows this origin."
      );
    }

    setLastUpdatedAt(new Date());
    setIsLoading(false);
  };

  const loadTransactionTabData = async ({
    page = transactionPage,
    dateFilter = transactionDateFilter,
    sort = transactionDateSort
  }: {
    page?: number;
    dateFilter?: typeof transactionDateFilter;
    sort?: typeof transactionDateSort;
  } = {}) => {
    setIsLoading(true);
    setApiError(null);

    const results = await Promise.allSettled([
      requestJson<ProductRow[]>("/products"),
      requestJson<SalesTrendPoint[]>("/dashboard/sales-trend?days=30"),
      requestJson<SaleTransactionPage>(buildSalesPath({ page, dateFilter, sort }))
    ]);

    const [productResult, salesResult, transactionResult] = results;

    if (productResult.status === "fulfilled") applyLoadedProducts(productResult.value);
    if (salesResult.status === "fulfilled") setSalesTrend(salesResult.value);
    if (transactionResult.status === "fulfilled") applyTransactionPage(transactionResult.value);

    const refreshFailed = results.some((item) => item.status === "rejected");
    if (refreshFailed) {
      setApiError("Sale was saved, but latest transaction data could not be refreshed.");
    }

    setLastUpdatedAt(new Date());
    setIsLoading(false);
    return !refreshFailed;
  };

  useEffect(() => {
    void checkAuth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (authState.status !== "authenticated") return;
    void loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authState.status]);

  useEffect(() => {
    if (authState.status === "authenticated" && !isAdminRole(authState.role) && activeTab === "settings") {
      setActiveTab("dashboard");
    }
  }, [activeTab, authState]);

  useEffect(() => {
    if (authState.status !== "authenticated" || newSale.ordered_by_username.trim()) return;
    setNewSale((prev) => ({ ...prev, ordered_by_username: authState.displayName }));
  }, [authState, newSale.ordered_by_username]);

  useEffect(() => {
    if (!scrapeJobId || !isScrapeJobRunning(scrapeJob)) return;

    let isCancelled = false;

    const pollScrapeJob = async () => {
      try {
        const nextJob = await requestJson<ManualScrapeJobStatus>(`/prices/scrape/jobs/${scrapeJobId}`);
        if (isCancelled) return;

        setScrapeJob(nextJob);
        setIsScraping(isScrapeJobRunning(nextJob));

        if (nextJob.status === "completed") {
          setActionMessage(`Manual web scraping completed. ${nextJob.inserted_rows} competitor price snapshots saved.`);
          await loadData();
        }
        if (nextJob.status === "failed") {
          setActionMessage(nextJob.error ? `Manual web scraping failed: ${nextJob.error}` : nextJob.message);
        }
      } catch (error) {
        if (!isCancelled) {
          setIsScraping(false);
          setActionMessage(`Manual web scraping status check failed: ${String(error)}`);
        }
      }
    };

    void pollScrapeJob();
    const intervalId = window.setInterval(() => void pollScrapeJob(), SCRAPE_JOB_POLL_INTERVAL_MS);

    return () => {
      isCancelled = true;
      window.clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrapeJobId, scrapeJob?.status]);

  useEffect(() => {
    if (selectedForecastProductId === null) return;

    let isCancelled = false;

    const loadItemForecast = async () => {
      setForecastModalError(null);
      setIsForecastModalLoading(true);

      try {
        const detail = await requestJson<ItemForecastDetail>(
          `/dashboard/item-forecast/${selectedForecastProductId}?history_days=${ITEM_FORECAST_HISTORY_DAYS}`
        );

        if (!isCancelled) {
          setSelectedForecastItem(detail);
        }
      } catch (error) {
        if (!isCancelled) {
          setForecastModalError(`Unable to load item forecast: ${String(error)}`);
        }
      } finally {
        if (!isCancelled) {
          setIsForecastModalLoading(false);
        }
      }
    };

    void loadItemForecast();

    return () => {
      isCancelled = true;
    };
  }, [selectedForecastProductId]);

  const onCreateProduct = async (event: FormEvent) => {
    event.preventDefault();
    setActionMessage(null);
    try {
      await requestJson<ProductRow>("/products", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...newProduct,
          category: newProduct.category || null,
          cost_price: Number(newProduct.cost_price),
          sell_price: Number(newProduct.sell_price),
          initial_stock: Number(newProduct.initial_stock),
          reorder_min_qty: Number(newProduct.reorder_min_qty),
          reorder_multiple: Number(newProduct.reorder_multiple),
          safety_stock: Number(newProduct.safety_stock)
        })
      });
      setActionMessage("Product created.");
      setNewProduct({
        sku: "",
        name: "",
        category: "",
        cost_price: "0.00",
        sell_price: "0.00",
        initial_stock: "0",
        reorder_min_qty: "1",
        reorder_multiple: "1",
        safety_stock: "0"
      });
      await loadData();
    } catch (error) {
      setActionMessage(`Create product failed: ${String(error)}`);
    }
  };

  const onAdjustStock = async (event: FormEvent) => {
    event.preventDefault();
    setActionMessage(null);
    try {
      await requestJson("/inventory/adjust", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: Number(adjustStock.product_id),
          qty_delta: Number(adjustStock.qty_delta),
          reason: adjustStock.reason
        })
      });
      setActionMessage("Stock adjusted.");
      setAdjustStock((prev) => ({ ...prev, qty_delta: "" }));
      await loadData();
    } catch (error) {
      setActionMessage(`Adjust stock failed: ${String(error)}`);
    }
  };

  const onSaveProduct = async (productId: number, payload: InventoryProductUpdatePayload) => {
    setActionMessage(null);
    try {
      await requestJson<ProductRow>(`/products/${productId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      await loadData();
      setActionMessage("Product updated.");
    } catch (error) {
      setActionMessage(`Update product failed: ${String(error)}`);
      throw error;
    }
  };

  const onDeleteProduct = async (productId: number) => {
    setActionMessage(null);
    try {
      await requestJson<ProductRow>(`/products/${productId}`, {
        method: "DELETE"
      });
      await loadData();
      setActionMessage("Product moved to recycle bin.");
    } catch (error) {
      setActionMessage(`Delete product failed: ${String(error)}`);
      throw error;
    }
  };

  const onRecordSale = async (event: FormEvent) => {
    event.preventDefault();
    setActionMessage(null);
    try {
      await requestJson("/sales", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          payment_method: newSale.payment_method,
          ordered_by_username: newSale.ordered_by_username.trim(),
          items: [
            {
              product_id: Number(newSale.product_id),
              qty: Number(newSale.qty)
            }
          ]
        })
      });
      setNewSale((prev) => ({ ...prev, qty: "1" }));
      setTransactionDateSort("desc");
      const refreshed = await loadTransactionTabData({ page: 1, sort: "desc" });
      setActionMessage(refreshed ? "Sale recorded." : "Sale recorded, but the transaction table did not fully refresh.");
    } catch (error) {
      setActionMessage(`Record sale failed: ${String(error)}`);
    }
  };

  const onOpenItemForecast = (productId: number) => {
    setSelectedForecastProductId(productId);
    setSelectedForecastItem(null);
    setForecastModalError(null);
  };

  const onCloseItemForecast = () => {
    setSelectedForecastProductId(null);
    setSelectedForecastItem(null);
    setForecastModalError(null);
    setIsForecastModalLoading(false);
  };

  const onRunManualScrape = async () => {
    setActionMessage(null);
    setApiError(null);
    setIsScraping(true);
    setIsScrapeConsoleOpen(false);
    try {
      const job = await requestJson<ManualScrapeJobStatus>("/prices/scrape/jobs", { method: "POST" });
      setScrapeJob(job);
      setScrapeJobId(job.job_id);
      setIsScraping(isScrapeJobRunning(job));
    } catch (error) {
      setActionMessage(`Manual web scraping failed: ${String(error)}`);
      setScrapeJob(null);
      setScrapeJobId(null);
      setIsScraping(false);
    }
  };

  const onCloseScrapeModal = () => {
    if (isScrapeJobRunning(scrapeJob)) return;
    setScrapeJob(null);
    setScrapeJobId(null);
    setIsScrapeConsoleOpen(false);
  };

  const onToggleScrapeConsole = () => {
    setIsScrapeConsoleOpen((prev) => !prev);
  };

  const formatScrapeElapsed = (job: ManualScrapeJobStatus | null) => {
    if (!job) return "--";
    const startedAt = new Date(job.started_at).getTime();
    if (Number.isNaN(startedAt)) return "--";
    const finishedAt = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
    const elapsedSeconds = Math.max(0, Math.floor((finishedAt - startedAt) / 1000));
    const minutes = Math.floor(elapsedSeconds / 60);
    const seconds = elapsedSeconds % 60;
    if (minutes <= 0) return `${seconds}s`;
    return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
  };

  const scrapeModalTitle = (() => {
    if (!scrapeJob) return "Manual Web Scrape";
    if (scrapeJob.status === "completed") return "Manual Web Scrape Complete";
    if (scrapeJob.status === "failed") return "Manual Web Scrape Failed";
    return "Manual Web Scrape";
  })();

  const scrapeProgressLabel = (() => {
    if (!scrapeJob) return "0%";
    if (scrapeJob.total_sources > 0) {
      return `${scrapeJob.completed_sources}/${scrapeJob.total_sources} sources`;
    }
    return `${scrapeJob.progress_pct}%`;
  })();
  const scrapeCurrentLabel = (() => {
    if (!scrapeJob) return "Waiting to start";
    if (scrapeJob.current_source) return scrapeJob.current_source;
    if (scrapeJob.status === "completed") return "Completed";
    if (scrapeJob.status === "failed") return "Failed";
    return "Preparing sources";
  })();

  const onChangeTransactionDateFilter = (field: "from" | "to", value: string) => {
    const nextFilter = { ...transactionDateFilter, [field]: value };
    setTransactionPage(1);
    setTransactionDateFilter(nextFilter);
    void loadTransactionPage({ page: 1, dateFilter: nextFilter });
  };

  const onToggleTransactionDateSort = () => {
    const nextSort = transactionDateSort === "desc" ? "asc" : "desc";
    setTransactionPage(1);
    setTransactionDateSort(nextSort);
    void loadTransactionPage({ page: 1, sort: nextSort });
  };

  const onCloseTransactionDetails = () => {
    setSelectedTransactionItemId(null);
  };

  const onChangeTransactionPage = (page: number) => {
    void loadTransactionPage({ page });
  };

  if (authState.status !== "authenticated") {
    return (
      <AdminLogin
        error={loginError}
        isChecking={authState.status === "checking"}
        isSubmitting={isLoggingIn}
        onSubmit={onAdminLogin}
      />
    );
  }

  return (
    <main className="dashboard-shell">
      <header className="hero">
        <p className="kicker">Stock Sage</p>
        <h1>Local Inventory Intelligence</h1>
        <p>Inventory operations, transaction capture, and AI-assisted forecasting in one local app.</p>
        <div className="toolbar">
          <div className="tab-group">
            <button
              className={activeTab === "dashboard" ? "tab active" : "tab"}
              onClick={() => setActiveTab("dashboard")}
            >
              📊 Dashboard
            </button>
            <button
              className={activeTab === "inventory" ? "tab active" : "tab"}
              onClick={() => setActiveTab("inventory")}
            >
              📦 Inventory
            </button>
            <button
              className={activeTab === "transactions" ? "tab active" : "tab"}
              onClick={() => setActiveTab("transactions")}
            >
              💳 Transactions
            </button>
            {isAdminRole(authState.role) ? (
              <button
                className={activeTab === "settings" ? "tab active" : "tab"}
                onClick={() => setActiveTab("settings")}
              >
                Settings
              </button>
            ) : null}
          </div>
          <button className="refresh-btn" onClick={() => void loadData()}>
            Refresh Data
          </button>
          <button className="secondary-btn" disabled={isScraping} onClick={() => void onRunManualScrape()}>
            {isScraping ? "Scraping..." : "Run Web Scrape"}
          </button>
          <button className="secondary-btn" onClick={() => void onLogout()}>
            Sign Out
          </button>
        </div>
        <div className="meta-row">
          <p className="meta account-meta">
            <span>Logged in as:</span>
            <span>{authState.displayName}</span>
            <span className={`role-pill role-pill--${authState.role}`}>{authState.role.replace("_", " ")}</span>
          </p>
          <p className="meta">{lastUpdatedLabel}</p>
        </div>
        {apiError ? <p className="status status-error">{apiError}</p> : null}
        {isLoading ? <p className="status">Loading latest data...</p> : null}
        {actionMessage ? <p className="status">{actionMessage}</p> : null}

        {activeTab === "dashboard" ? (
          <>
            <section className="kpi-grid" aria-label="Dashboard KPIs">
              <article className="kpi-card">
                <p className="kpi-label">📦 Inventory Value</p>
                <p className="kpi-value">{formatPHPCompact(totalInventoryValue)}</p>
              </article>
              <article className="kpi-card">
                <p className="kpi-label">⚠ Low Stock Items</p>
                <p className={lowStockCount > 0 ? "kpi-value kpi-value--warn" : "kpi-value"}>{lowStockCount}</p>
                <p className="kpi-sub">Out of stock: {outOfStockCount}</p>
              </article>
              <article className="kpi-card">
                <p className="kpi-label">💰 Revenue Today</p>
                <p className="kpi-value">{formatPHPCompact(revenueToday)}</p>
              </article>
              <article className="kpi-card">
                <p className="kpi-label">📊 Products</p>
                <p className="kpi-value">{products.length}</p>
              </article>
            </section>

            {upcomingStockoutsCount > 0 ? (
              <div className="action-banner action-banner--warn">
                <div>
                  <p className="action-banner-title">
                    <span className="action-banner-icon">⚠</span> {upcomingStockoutsCount} Products Will Stock Out Within 5 Days
                  </p>
                  <p className="action-banner-copy">Review forecast and generate purchase orders.</p>
                </div>
                <button
                  className="primary-btn action-banner-btn"
                  onClick={() => {
                    setActiveTab("inventory");
                    setActionMessage("Inventory tab opened for purchase planning.");
                  }}
                >
                  Generate Purchase Plan
                </button>
              </div>
            ) : (
              <div className="action-banner action-banner--ok">
                <div>
                  <p className="action-banner-title">✅ No stockout risk in the next 5 days</p>
                  <p className="action-banner-copy">Inventory health is stable for the current forecast horizon.</p>
                </div>
              </div>
            )}
          </>
        ) : null}
      </header>

      {activeTab === "dashboard" ? (
        <section className="dashboard-grid dashboard-grid--overview">
          <LowStockTable rows={lowStock} onSelectProduct={onOpenItemForecast} />
          <StockoutCard rows={stockoutRows} onSelectProduct={onOpenItemForecast} />
          <PriceComparisonTable rows={priceRows} onSelectProduct={onOpenItemForecast} />
        </section>
      ) : null}

      {activeTab === "dashboard" ? (
        <section className="dashboard-grid dashboard-grid--source-quality">
          <SourceQualityPanel rows={sourceQualityRows} windowHours={24} />
        </section>
      ) : null}

      {activeTab === "inventory" ? (
        <section className="dashboard-grid dashboard-grid--inventory">
          <section className="panel inventory-card inventory-card--create">
            <h2>Add Product</h2>
            <form className="form-grid form-grid-2" onSubmit={onCreateProduct}>
              <label>
                SKU
                <input
                  value={newProduct.sku}
                  onChange={(event) => setNewProduct((prev) => ({ ...prev, sku: event.target.value }))}
                  required
                />
              </label>
              <label>
                Name
                <input
                  value={newProduct.name}
                  onChange={(event) => setNewProduct((prev) => ({ ...prev, name: event.target.value }))}
                  required
                />
              </label>
              <label>
                Category
                <select
                  value={newProduct.category}
                  onChange={(event) => setNewProduct((prev) => ({ ...prev, category: event.target.value }))}
                >
                  <option value="">Select category</option>
                  {PRODUCT_CATEGORY_OPTIONS.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Cost Price
                <input
                  type="number"
                  step="0.01"
                  value={newProduct.cost_price}
                  onChange={(event) => setNewProduct((prev) => ({ ...prev, cost_price: event.target.value }))}
                  required
                />
              </label>
              <label>
                Sell Price
                <input
                  type="number"
                  step="0.01"
                  value={newProduct.sell_price}
                  onChange={(event) => setNewProduct((prev) => ({ ...prev, sell_price: event.target.value }))}
                  required
                />
              </label>
              <label>
                Initial Stock
                <input
                  type="number"
                  value={newProduct.initial_stock}
                  onChange={(event) => setNewProduct((prev) => ({ ...prev, initial_stock: event.target.value }))}
                  required
                />
              </label>
              <label>
                Reorder Min Qty
                <input
                  type="number"
                  value={newProduct.reorder_min_qty}
                  onChange={(event) => setNewProduct((prev) => ({ ...prev, reorder_min_qty: event.target.value }))}
                  required
                />
              </label>
              <label>
                Reorder Multiple
                <input
                  type="number"
                  value={newProduct.reorder_multiple}
                  onChange={(event) => setNewProduct((prev) => ({ ...prev, reorder_multiple: event.target.value }))}
                  required
                />
              </label>
              <label>
                Safety Stock
                <input
                  type="number"
                  value={newProduct.safety_stock}
                  onChange={(event) => setNewProduct((prev) => ({ ...prev, safety_stock: event.target.value }))}
                  required
                />
              </label>
              <button type="submit" className="primary-btn form-submit">
                Create Product
              </button>
            </form>
          </section>

          <section className="panel inventory-card inventory-card--adjust">
            <h2>Adjust Stock</h2>
            <form className="form-grid" onSubmit={onAdjustStock}>
              <label>
                Product
                <select
                  value={adjustStock.product_id}
                  onChange={(event) => setAdjustStock((prev) => ({ ...prev, product_id: event.target.value }))}
                  required
                >
                  <option value="">Select product</option>
                  {products.map((product) => (
                    <option key={product.id} value={String(product.id)}>
                      {product.sku} - {product.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Quantity Delta
                <input
                  type="number"
                  value={adjustStock.qty_delta}
                  onChange={(event) => setAdjustStock((prev) => ({ ...prev, qty_delta: event.target.value }))}
                  placeholder="Use negative for decrease"
                  required
                />
              </label>
              <label>
                Reason
                <input
                  value={adjustStock.reason}
                  onChange={(event) => setAdjustStock((prev) => ({ ...prev, reason: event.target.value }))}
                />
              </label>
              <button type="submit" className="primary-btn">
                Apply Adjustment
              </button>
            </form>
          </section>

          <InventoryProductsTable
            canDeleteProducts={isAdminRole(authState.role)}
            formatPHP={formatPHP}
            onDeleteProduct={onDeleteProduct}
            onSaveProduct={onSaveProduct}
            products={products}
          />
        </section>
      ) : null}

      {activeTab === "transactions" ? (
        <section className="dashboard-grid dashboard-grid--transactions">
          <section className="panel transactions-card transactions-card--sale">
            <h2>Record Sale</h2>
            <form className="form-grid" onSubmit={onRecordSale}>
              <label>
                Product
                <select
                  value={newSale.product_id}
                  onChange={(event) => setNewSale((prev) => ({ ...prev, product_id: event.target.value }))}
                  required
                >
                  <option value="">Select product</option>
                  {products.map((product) => (
                    <option key={product.id} value={String(product.id)}>
                      {product.sku} - {product.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Quantity
                <input
                  type="number"
                  value={newSale.qty}
                  min={1}
                  onChange={(event) => setNewSale((prev) => ({ ...prev, qty: event.target.value }))}
                  required
                />
              </label>
              <label>
                Ordered By
                <input
                  value={newSale.ordered_by_username}
                  onChange={(event) => setNewSale((prev) => ({ ...prev, ordered_by_username: event.target.value }))}
                  required
                />
              </label>
              <label>
                Payment Method
                <select
                  value={newSale.payment_method}
                  onChange={(event) => setNewSale((prev) => ({ ...prev, payment_method: event.target.value }))}
                >
                  <option value="cash">cash</option>
                  <option value="card">card</option>
                  <option value="online">online</option>
                </select>
              </label>
              <button type="submit" className="primary-btn">
                Save Sale
              </button>
            </form>
          </section>

          <section className="panel panel-wide transactions-card transactions-card--snapshot">
            <h2>Current Inventory Snapshot</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Name</th>
                    <th>On Hand</th>
                  </tr>
                </thead>
                <tbody>
                  {products.length === 0 ? (
                    <tr>
                      <td colSpan={3}>No products loaded.</td>
                    </tr>
                  ) : (
                    products.map((product) => (
                      <tr key={product.id}>
                        <td>{product.sku}</td>
                        <td>{product.name}</td>
                        <td>{product.on_hand_qty}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel panel-wide transactions-card transactions-card--history">
            <div className="panel-head transaction-history-head">
              <div>
                <h2>Transaction History</h2>
                <p className="meta transaction-history-copy">Sales saved from Record Sale appear here.</p>
              </div>
              <div className="transaction-filters" aria-label="Transaction date filters">
                <label className="transaction-filter-label">
                  From
                  <input
                    type="date"
                    value={transactionDateFilter.from}
                    onChange={(event) => onChangeTransactionDateFilter("from", event.target.value)}
                  />
                </label>
                <label className="transaction-filter-label">
                  To
                  <input
                    type="date"
                    value={transactionDateFilter.to}
                    onChange={(event) => onChangeTransactionDateFilter("to", event.target.value)}
                  />
                </label>
                <button
                  type="button"
                  className="secondary-btn transaction-sort-toggle"
                  onClick={onToggleTransactionDateSort}
                >
                  {transactionDateSort === "desc" ? "Latest first" : "Oldest first"}
                </button>
              </div>
            </div>
            <div className="table-wrap transaction-table-wrap">
              <table className="transactions-table" aria-label="Transaction history">
                <thead>
                  <tr>
                    <th>
                      <button
                        type="button"
                        className="table-sort-btn"
                        onClick={onToggleTransactionDateSort}
                        aria-label={`Sort transactions by date, ${
                          transactionDateSort === "desc" ? "oldest first" : "latest first"
                        }`}
                      >
                        Date
                        <span>{transactionDateSort === "desc" ? "Latest" : "Oldest"}</span>
                      </button>
                    </th>
                    <th>Product</th>
                    <th>Ordered By</th>
                    <th className="align-right">Quantity</th>
                    <th className="align-right">Unit Price</th>
                    <th className="align-right">Total</th>
                    <th className="transaction-actions-head">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {transactionRows.length === 0 ? (
                    <tr>
                      <td colSpan={7}>
                        {isTransactionLoading
                          ? "Loading transactions..."
                          : transactionTotal === 0 && (transactionDateFilter.from || transactionDateFilter.to)
                            ? "No transactions match this date range."
                            : "No transactions recorded yet."}
                      </td>
                    </tr>
                  ) : (
                    transactionRows.map((transaction) => (
                      <tr key={transaction.item_id}>
                        <td className="transaction-date">{formatTransactionDate(transaction.sold_at)}</td>
                        <td>
                          <div className="transaction-product-cell">
                            <span className="transaction-product-name">{transaction.product_name}</span>
                            <span className="transaction-product-sku">{transaction.sku}</span>
                          </div>
                        </td>
                        <td>{transaction.ordered_by_username?.trim() || "N/A"}</td>
                        <td className="align-right">{transaction.qty}</td>
                        <td className="align-right">{formatPHPWhole(transaction.unit_sell_price)}</td>
                        <td className="align-right transaction-total">{formatPHPWhole(transaction.line_total)}</td>
                        <td className="transaction-actions">
                          <button
                            type="button"
                            className="icon-action-btn"
                            aria-label={`View receipt ${transaction.receipt_no}`}
                            title={`View receipt ${transaction.receipt_no}`}
                            onClick={() => setSelectedTransactionItemId(transaction.item_id)}
                          >
                            <svg
                              aria-hidden="true"
                              focusable="false"
                              width="18"
                              height="18"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth={2}
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
                              <circle cx="12" cy="12" r="3" />
                            </svg>
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <div className="transaction-pagination" aria-label="Transaction pagination">
              <p className="meta">
                Showing {transactionRangeStart}-{transactionRangeEnd} of {transactionTotal} transactions
              </p>
              <div className="transaction-pagination-actions">
                <button
                  type="button"
                  className="secondary-btn"
                  disabled={isTransactionLoading || normalizedTransactionPage <= 1}
                  onClick={() => onChangeTransactionPage(Math.max(1, normalizedTransactionPage - 1))}
                >
                  Previous
                </button>
                <span className="transaction-page-count">
                  Page {normalizedTransactionPage} of {transactionPageCount}
                </span>
                <button
                  type="button"
                  className="secondary-btn"
                  disabled={isTransactionLoading || normalizedTransactionPage >= transactionPageCount}
                  onClick={() => onChangeTransactionPage(Math.min(transactionPageCount, normalizedTransactionPage + 1))}
                >
                  Next
                </button>
              </div>
            </div>
          </section>
        </section>
      ) : null}

      {activeTab === "settings" && isAdminRole(authState.role) ? (
        <SettingsPanel
          currentRole={authState.role}
          currentUsername={authState.username}
          requestJson={requestJson}
          onProductsChanged={loadData}
        />
      ) : null}

      {scrapeJob ? (
        <div
          className="modal-overlay"
          role="presentation"
          onClick={isScrapeJobRunning(scrapeJob) ? undefined : onCloseScrapeModal}
        >
          <section
            className="modal-card scrape-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="scrape-modal-title"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="modal-close-btn"
              type="button"
              onClick={onCloseScrapeModal}
              aria-label="Close manual web scrape progress"
              disabled={isScrapeJobRunning(scrapeJob)}
              title={isScrapeJobRunning(scrapeJob) ? "Scrape is still running" : "Close"}
            >
              x
            </button>
            <div className="modal-header scrape-modal-header">
              <p className="kpi-label">Web Scraper</p>
              <h2 id="scrape-modal-title">{scrapeModalTitle}</h2>
              <p className="meta">{scrapeJob.message}</p>
            </div>

            <div className="scrape-progress-summary">
              <article className="modal-metric">
                <p className="kpi-label">Progress</p>
                <p className="settings-stat-value">{scrapeJob.progress_pct}%</p>
              </article>
              <article className="modal-metric">
                <p className="kpi-label">Snapshots</p>
                <p className="settings-stat-value">{scrapeJob.inserted_rows}</p>
              </article>
              <article className="modal-metric">
                <p className="kpi-label">Elapsed</p>
                <p className="settings-stat-value">{formatScrapeElapsed(scrapeJob)}</p>
              </article>
            </div>

            <div className="scrape-progress-block">
              <div className="scrape-progress-line">
                <span>{scrapeCurrentLabel}</span>
                <span>{scrapeProgressLabel}</span>
              </div>
              <div
                className="scrape-progress-track"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={scrapeJob.progress_pct}
                aria-label="Manual web scrape progress"
              >
                <div className="scrape-progress-fill" style={{ width: `${scrapeJob.progress_pct}%` }} />
              </div>
            </div>

            {scrapeJob.status === "failed" ? (
              <p className="status status-error scrape-modal-error">{scrapeJob.error ?? scrapeJob.message}</p>
            ) : null}

            <div className="scrape-console-shell">
              <button className="secondary-btn scrape-console-toggle" type="button" onClick={onToggleScrapeConsole}>
                {isScrapeConsoleOpen ? "Hide Debug Console" : "Show Debug Console"}
              </button>
              {isScrapeConsoleOpen ? (
                <pre className="scrape-debug-console" aria-label="Manual web scrape debug console">
                  {scrapeJob.logs.length > 0 ? scrapeJob.logs.join("\n") : "No debug logs yet."}
                </pre>
              ) : null}
            </div>

            {!isScrapeJobRunning(scrapeJob) ? (
              <div className="scrape-modal-actions">
                <button className="primary-btn" type="button" onClick={onCloseScrapeModal}>
                  Close
                </button>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      <ForecastItemModal
        isOpen={selectedForecastProductId !== null}
        item={selectedForecastItem}
        isLoading={isForecastModalLoading}
        error={forecastModalError}
        onClose={onCloseItemForecast}
      />

      {selectedTransaction ? (
        <div className="modal-overlay" role="presentation" onClick={onCloseTransactionDetails}>
          <section
            className="modal-card modal-card--state transaction-detail-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="transaction-detail-title"
            onClick={(event) => event.stopPropagation()}
          >
            <button className="modal-close-btn" type="button" onClick={onCloseTransactionDetails} aria-label="Close receipt details">
              x
            </button>
            <div className="modal-header">
              <p className="kpi-label">Receipt</p>
              <h2 id="transaction-detail-title">{selectedTransaction.receipt_no}</h2>
              <p className="meta">{formatTransactionDateTime(selectedTransaction.sold_at)}</p>
            </div>
            <div className="transaction-detail-grid">
              <article className="modal-metric">
                <p className="kpi-label">Payment</p>
                <p className="settings-stat-value">{selectedTransaction.payment_method ?? "-"}</p>
              </article>
              <article className="modal-metric">
                <p className="kpi-label">Ordered By</p>
                <p className="settings-stat-value">{selectedTransaction.ordered_by_username?.trim() || "N/A"}</p>
              </article>
              <article className="modal-metric">
                <p className="kpi-label">Transaction Total</p>
                <p className="settings-stat-value">{formatPHPWhole(selectedTransaction.total_amount)}</p>
              </article>
            </div>
            <div className="table-wrap transaction-detail-table-wrap">
              <table className="transactions-table">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="align-right">Quantity</th>
                    <th className="align-right">Unit Price</th>
                    <th className="align-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>
                      <div className="transaction-product-cell">
                        <span className="transaction-product-name">{selectedTransaction.product_name}</span>
                        <span className="transaction-product-sku">{selectedTransaction.sku}</span>
                      </div>
                    </td>
                    <td className="align-right">{selectedTransaction.qty}</td>
                    <td className="align-right">{formatPHPWhole(selectedTransaction.unit_sell_price)}</td>
                    <td className="align-right transaction-total">{formatPHPWhole(selectedTransaction.line_total)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
};

export default App;
