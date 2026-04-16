import { FormEvent, useEffect, useState } from "react";
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
  ProductRow,
  LowStockRow,
  PriceComparisonRow,
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
      `Cannot reach API at ${API_BASE_URL}. Check that the backend URL is live and CORS allows this frontend. Original error: ${String(error)}`
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

  const [activeTab, setActiveTab] = useState<"dashboard" | "inventory" | "transactions" | "settings">("dashboard");
  const [authState, setAuthState] = useState<AuthState>({ status: "checking" });
  const [loginError, setLoginError] = useState<string | null>(null);
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const [lowStock, setLowStock] = useState<LowStockRow[]>([]);
  const [stockoutRows, setStockoutRows] = useState<StockoutRow[]>([]);
  const [priceRows, setPriceRows] = useState<PriceComparisonRow[]>([]);
  const [salesTrend, setSalesTrend] = useState<SalesTrendPoint[]>([]);
  const [products, setProducts] = useState<ProductRow[]>([]);
  const [sourceQualityRows, setSourceQualityRows] = useState<ScraperSourceQualityRow[]>([]);
  const [selectedForecastProductId, setSelectedForecastProductId] = useState<number | null>(null);
  const [selectedForecastItem, setSelectedForecastItem] = useState<ItemForecastDetail | null>(null);
  const [isForecastModalLoading, setIsForecastModalLoading] = useState<boolean>(false);
  const [forecastModalError, setForecastModalError] = useState<string | null>(null);

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
    setProducts([]);
    setSourceQualityRows([]);
    setSelectedForecastProductId(null);
    setSelectedForecastItem(null);
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
      setLoginError(`Cannot check admin session at ${API_BASE_URL}: ${String(error)}`);
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
      requestJson<ScraperSourceQualityRow[]>("/dashboard/scraper-source-quality?window_hours=24")
    ]);

    const [lowStockResult, stockoutResult, priceResult, salesResult, productResult, sourceQualityResult] = results;

    if (lowStockResult.status === "fulfilled") setLowStock(lowStockResult.value);
    if (stockoutResult.status === "fulfilled") setStockoutRows(stockoutResult.value);
    if (priceResult.status === "fulfilled") setPriceRows(priceResult.value);
    if (salesResult.status === "fulfilled") setSalesTrend(salesResult.value);
    if (productResult.status === "fulfilled") {
      setProducts(productResult.value);
      if (!adjustStock.product_id && productResult.value.length > 0) {
        setAdjustStock((prev) => ({ ...prev, product_id: String(productResult.value[0].id) }));
      }
      if (!newSale.product_id && productResult.value.length > 0) {
        setNewSale((prev) => ({ ...prev, product_id: String(productResult.value[0].id) }));
      }
    }
    if (sourceQualityResult.status === "fulfilled") setSourceQualityRows(sourceQualityResult.value);

    const firstError = results.find((item) => item.status === "rejected");
    if (firstError && firstError.status === "rejected") {
      setApiError(
        `Cannot load API data from ${API_BASE_URL}. Ensure backend is running and CORS allows this origin.`
      );
    }

    setLastUpdatedAt(new Date());
    setIsLoading(false);
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
    if (authState.status === "authenticated" && authState.role !== "admin" && activeTab === "settings") {
      setActiveTab("dashboard");
    }
  }, [activeTab, authState]);

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
          items: [
            {
              product_id: Number(newSale.product_id),
              qty: Number(newSale.qty)
            }
          ]
        })
      });
      setActionMessage("Sale recorded.");
      setNewSale((prev) => ({ ...prev, qty: "1" }));
      await loadData();
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

  if (authState.status !== "authenticated") {
    return (
      <AdminLogin
        apiBaseUrl={API_BASE_URL}
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
            {authState.role === "admin" ? (
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
          <button className="secondary-btn" onClick={() => void onLogout()}>
            Sign Out
          </button>
        </div>
        <div className="meta-row">
          <p className="meta account-meta">
            <span>{authState.displayName}</span>
            <span className={`role-pill role-pill--${authState.role}`}>{authState.role}</span>
          </p>
          <p className="meta">API: {API_BASE_URL}</p>
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
            canDeleteProducts={authState.role === "admin"}
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
        </section>
      ) : null}

      {activeTab === "settings" && authState.role === "admin" ? (
        <SettingsPanel requestJson={requestJson} onProductsChanged={loadData} />
      ) : null}

      <ForecastItemModal
        isOpen={selectedForecastProductId !== null}
        item={selectedForecastItem}
        isLoading={isForecastModalLoading}
        error={forecastModalError}
        onClose={onCloseItemForecast}
      />
    </main>
  );
};

export default App;
