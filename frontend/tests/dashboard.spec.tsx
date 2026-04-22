import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../src/App";

const toDateString = (baseDate: Date, offsetDays: number) => {
  const date = new Date(baseDate);
  date.setUTCDate(date.getUTCDate() + offsetDays);
  return date.toISOString().slice(0, 10);
};

const buildItemForecastDetail = (historyDays: number) => ({
  product_id: 1,
  sku: "SKU-LOW-1",
  name: "Low Stock Item",
  forecast_horizon_days: 30,
  predicted_per_month: 90,
  in_stock: 4,
  reorder_qty: 10,
  confidence_pct: 75,
  predicted_stockout_date: "2026-04-12",
  days_until_stockout: 2,
  when_to_buy_message: "Order 10 units now.",
  demand_points: [
    ...Array.from({ length: historyDays }, (_, index) => ({
      date: toDateString(new Date("2025-09-01T00:00:00.000Z"), index),
      units: (index % 4) + 1,
      kind: "history" as const
    })),
    ...Array.from({ length: 30 }, (_, index) => ({
      date: toDateString(new Date("2026-04-01T00:00:00.000Z"), index),
      units: 2 + (index % 3),
      kind: "forecast" as const
    }))
  ],
  price_analysis: {
    store_price: "3000.00",
    market_avg_price: "2950.00",
    difference_pct: "1.69",
    suggested_price: null,
    competitor_benchmarks: []
  }
});

describe("Dashboard rendering", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        return {
          ok: true,
          json: async () =>
            url.includes("/auth/me")
              ? { authenticated: true, configured: true, username: "admin", display_name: "Admin User", role: "admin" }
              : []
        };
      })
    );
  });

  it("requires admin login before rendering dashboard content", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        return {
          ok: true,
          json: async () =>
            url.includes("/auth/me")
              ? { authenticated: false, configured: true, username: null, display_name: null, role: null }
              : []
        };
      })
    );

    render(<App />);

    expect(await screen.findByText("Admin access")).toBeInTheDocument();
    expect(screen.queryByText("Low Stock Alerts")).not.toBeInTheDocument();
  });

  it("renders all major dashboard sections", async () => {
    render(<App />);

    expect(await screen.findByText("Low Stock Alerts")).toBeInTheDocument();
    expect(await screen.findByText("Predicted Stockout Timeline")).toBeInTheDocument();
    expect(await screen.findByText("Price Comparison Results")).toBeInTheDocument();
    expect(screen.queryByText("Sales Trend")).not.toBeInTheDocument();
  });

  it("runs manual web scraping from the dashboard toolbar", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.includes("/auth/me")) {
        return {
          ok: true,
          json: async () => ({ authenticated: true, configured: true, username: "admin", display_name: "Admin User", role: "admin" })
        };
      }

      if (url.endsWith("/prices/scrape") && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            inserted_rows: 3,
            ran_at: "2026-04-22T00:00:00Z",
            message: "Manual web scraping completed with 3 snapshots saved."
          })
        };
      }

      return {
        ok: true,
        json: async () => []
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /run web scrape/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/prices/scrape"),
        expect.objectContaining({ method: "POST" })
      );
    });
    expect(await screen.findByText("Manual web scraping completed. 3 competitor price snapshots saved.")).toBeInTheDocument();
  });

  it("does not render the developer forecast metrics report controls", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return {
        ok: true,
        json: async () =>
          url.includes("/auth/me")
            ? { authenticated: true, configured: true, username: "admin", display_name: "Admin User", role: "admin" }
            : []
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("Low Stock Alerts")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate forecast report/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Developer Forecast Metrics Report")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/dashboard/forecast-report"))).toBe(false);
  });

  it("renders the add product category field as a dropdown", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /inventory/i }));

    const categorySelect = await screen.findByLabelText("Category");
    expect(categorySelect.tagName).toBe("SELECT");

    const options = screen.getAllByRole("option").map((option) => option.textContent);
    expect(options).toEqual(
      expect.arrayContaining(["Select category", "Case", "Cooler", "CPU", "GPU", "Motherboard", "PSU", "RAM", "SSD"])
    );
  });

  it("shows sales in transaction history, filters by date, and refreshes after recording a sale", async () => {
    const products = [
      {
        id: 1,
        sku: "RAM-8GB",
        name: "8GB DDR4 RAM",
        category: "RAM",
        supplier_id: null,
        cost_price: "1200.00",
        sell_price: "1800.00",
        reorder_min_qty: 1,
        reorder_multiple: 1,
        safety_stock: 4,
        active: true,
        on_hand_qty: 8,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-02-02T00:00:00Z"
      },
      {
        id: 2,
        sku: "PSU-600W",
        name: "600W PSU",
        category: "PSU",
        supplier_id: null,
        cost_price: "1800.00",
        sell_price: "2600.00",
        reorder_min_qty: 1,
        reorder_multiple: 1,
        safety_stock: 2,
        active: true,
        on_hand_qty: 5,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-02-01T00:00:00Z"
      },
      {
        id: 3,
        sku: "SSD-240GB",
        name: "240GB SSD",
        category: "SSD",
        supplier_id: null,
        cost_price: "1200.00",
        sell_price: "1800.00",
        reorder_min_qty: 1,
        reorder_multiple: 1,
        safety_stock: 2,
        active: true,
        on_hand_qty: 7,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-02-03T00:00:00Z"
      }
    ];
    let transactionRows = [
      {
        transaction_id: 1,
        item_id: 1,
        receipt_no: "R-001",
        sold_at: "2026-02-01T08:00:00Z",
        product_id: 2,
        sku: "PSU-600W",
        product_name: "600W PSU",
        qty: 1,
        unit_sell_price: "2600.00",
        line_total: "2600.00",
        total_amount: "2600.00",
        payment_method: "cash",
        ordered_by_username: null
      },
      {
        transaction_id: 2,
        item_id: 2,
        receipt_no: "R-002",
        sold_at: "2026-02-02T09:00:00Z",
        product_id: 1,
        sku: "RAM-8GB",
        product_name: "8GB DDR4 RAM",
        qty: 1,
        unit_sell_price: "1800.00",
        line_total: "1800.00",
        total_amount: "1800.00",
        payment_method: "card",
        ordered_by_username: "admin"
      }
    ];
    const buildSalesPage = (url: string) => {
      const parsedUrl = new URL(url);
      const dateFrom = parsedUrl.searchParams.get("date_from") ?? "";
      const dateTo = parsedUrl.searchParams.get("date_to") ?? "";
      const sort = parsedUrl.searchParams.get("sort") ?? "desc";
      const page = Number(parsedUrl.searchParams.get("page") ?? "1");
      const pageSize = Number(parsedUrl.searchParams.get("page_size") ?? "50");
      const rows = [...transactionRows]
        .filter((transaction) => {
          const soldAtDate = transaction.sold_at.slice(0, 10);
          if (dateFrom && soldAtDate < dateFrom) return false;
          if (dateTo && soldAtDate > dateTo) return false;
          return true;
        })
        .sort((left, right) => {
          const dateDiff = new Date(left.sold_at).getTime() - new Date(right.sold_at).getTime();
          if (dateDiff !== 0) return sort === "asc" ? dateDiff : -dateDiff;
          return sort === "asc" ? left.item_id - right.item_id : right.item_id - left.item_id;
        });
      const start = (page - 1) * pageSize;

      return {
        items: rows.slice(start, start + pageSize),
        total: rows.length,
        page,
        page_size: pageSize,
        total_pages: Math.max(1, Math.ceil(rows.length / pageSize))
      };
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const pathname = new URL(url).pathname;

      if (url.includes("/auth/me")) {
        return {
          ok: true,
          json: async () => ({ authenticated: true, configured: true, username: "admin", display_name: "Admin User", role: "admin" })
        };
      }

      if (pathname === "/sales" && init?.method === "POST") {
        const payload = JSON.parse(String(init.body));
        const product = products.find((item) => item.id === payload.items[0].product_id) ?? products[0];
        transactionRows = [
          ...transactionRows,
          {
            transaction_id: 3,
            item_id: 3,
            receipt_no: "R-003",
            sold_at: "2026-02-03T10:00:00Z",
            product_id: product.id,
            sku: product.sku,
            product_name: product.name,
            qty: payload.items[0].qty,
            unit_sell_price: product.sell_price,
            line_total: product.sell_price,
            total_amount: product.sell_price,
            payment_method: payload.payment_method,
            ordered_by_username: "admin"
          }
        ];
        return {
          ok: true,
          json: async () => ({
            id: 3,
            receipt_no: "R-003",
            sold_at: "2026-02-03T10:00:00Z",
            total_amount: product.sell_price,
            payment_method: payload.payment_method,
            items: []
          })
        };
      }

      if (pathname === "/sales") {
        return {
          ok: true,
          json: async () => buildSalesPage(url)
        };
      }

      if (url.includes("/products")) {
        return {
          ok: true,
          json: async () => products
        };
      }

      return {
        ok: true,
        json: async () => []
      };
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /transactions/i }));

    const historyTable = await screen.findByRole("table", { name: /transaction history/i });
    const initialRows = within(historyTable).getAllByRole("row").map((row) => row.textContent ?? "");
    expect(initialRows[1]).toContain("8GB DDR4 RAM");
    expect(initialRows[1]).toContain("admin");
    expect(initialRows[2]).toContain("600W PSU");
    expect(initialRows[2]).toContain("N/A");

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-02-02" } });
    await waitFor(() => {
      expect(within(historyTable).getByText("8GB DDR4 RAM")).toBeInTheDocument();
      expect(within(historyTable).queryByText("600W PSU")).not.toBeInTheDocument();
    });

    fireEvent.click(within(historyTable).getByRole("button", { name: /view receipt R-002/i }));
    expect(await screen.findByRole("heading", { name: "R-002" })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Close receipt details"));

    fireEvent.change(screen.getByLabelText("Product"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /save sale/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/sales"),
        expect.objectContaining({ method: "POST" })
      );
    });
    expect(await screen.findByText("Sale recorded.")).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: /transaction history/i })).getByText("240GB SSD")).toBeInTheDocument();
  });

  it("allows editing a product from the inventory table", async () => {
    const product = {
      id: 1,
      sku: "CPU-AMD-3300",
      name: "AMD Ryzen 3 3200",
      category: "CPU",
      supplier_id: null,
      cost_price: "3200.00",
      sell_price: "4500.00",
      reorder_min_qty: 1,
      reorder_multiple: 1,
      safety_stock: 10,
      active: true,
      on_hand_qty: 19,
      created_at: "2026-04-09T00:00:00Z",
      updated_at: "2026-04-09T00:00:00Z"
    };

    let currentProduct = product;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.includes("/auth/me")) {
        return {
          ok: true,
          json: async () => ({ authenticated: true, configured: true, username: "admin", display_name: "Admin User", role: "admin" })
        };
      }

      if (url.endsWith("/products") && init?.method === "PATCH") {
        throw new Error("Unexpected bulk patch");
      }

      if (url.endsWith("/products/1") && init?.method === "PATCH") {
        const payload = JSON.parse(String(init.body));
        currentProduct = {
          ...currentProduct,
          ...payload
        };
        return {
          ok: true,
          json: async () => currentProduct
        };
      }

      if (url.includes("/products")) {
        return {
          ok: true,
          json: async () => [currentProduct]
        };
      }

      return {
        ok: true,
        json: async () => []
      };
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /inventory/i }));
    expect(await screen.findByText("AMD Ryzen 3 3200")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /edit product cpu-amd-3300/i }));
    fireEvent.change(screen.getByLabelText(/name for cpu-amd-3300/i), {
      target: { value: "AMD Ryzen 3 3200G" }
    });
    fireEvent.change(screen.getByLabelText(/sell price for cpu-amd-3300/i), {
      target: { value: "4999.00" }
    });
    fireEvent.change(screen.getByLabelText(/on hand for cpu-amd-3300/i), {
      target: { value: "22" }
    });
    fireEvent.click(screen.getByRole("button", { name: /save product cpu-amd-3300/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/products/1"),
        expect.objectContaining({
          method: "PATCH"
        })
      );
    });

    expect(await screen.findByText("Product updated.")).toBeInTheDocument();
    expect(await screen.findByText("AMD Ryzen 3 3200G")).toBeInTheDocument();
  });

  it("lets admins move products to the recycle bin and restore them from settings", async () => {
    const product = {
      id: 1,
      sku: "GPU-DELETE-1",
      name: "Deletable GPU",
      category: "GPU",
      supplier_id: null,
      cost_price: "12000.00",
      sell_price: "15000.00",
      reorder_min_qty: 1,
      reorder_multiple: 1,
      safety_stock: 2,
      active: true,
      on_hand_qty: 5,
      created_at: "2026-04-09T00:00:00Z",
      updated_at: "2026-04-09T00:00:00Z"
    };

    let activeProducts = [product];
    let recycledProducts: typeof activeProducts = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.includes("/auth/me")) {
        return {
          ok: true,
          json: async () => ({ authenticated: true, configured: true, username: "admin", display_name: "Admin User", role: "admin" })
        };
      }

      if (url.endsWith("/products/1") && init?.method === "DELETE") {
        const deletedProduct = { ...product, active: false };
        activeProducts = [];
        recycledProducts = [deletedProduct];
        return {
          ok: true,
          json: async () => deletedProduct
        };
      }

      if (url.endsWith("/settings/recycle-bin/products/1/restore") && init?.method === "POST") {
        const restoredProduct = { ...product, active: true };
        activeProducts = [restoredProduct];
        recycledProducts = [];
        return {
          ok: true,
          json: async () => restoredProduct
        };
      }

      if (url.endsWith("/settings/recycle-bin/products")) {
        return {
          ok: true,
          json: async () => recycledProducts
        };
      }

      if (url.includes("/settings/accounts") || url.includes("/settings/audit-logs")) {
        return {
          ok: true,
          json: async () => []
        };
      }

      if (url.includes("/settings/system")) {
        return {
          ok: true,
          json: async () => ({ auth_enabled: true, configured: true, active_accounts: 1, admin_accounts: 1, staff_accounts: 0, session_ttl_seconds: 86400 })
        };
      }

      if (url.includes("/products")) {
        return {
          ok: true,
          json: async () => activeProducts
        };
      }

      return {
        ok: true,
        json: async () => []
      };
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /inventory/i }));
    expect(await screen.findByText("Deletable GPU")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /delete product gpu-delete-1/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/products/1"),
        expect.objectContaining({ method: "DELETE" })
      );
    });
    expect(await screen.findByText("Product moved to recycle bin.")).toBeInTheDocument();
    expect(screen.queryByText("Deletable GPU")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /settings/i }));
    fireEvent.click(await screen.findByRole("button", { name: /recycle bin/i }));
    expect(await screen.findByText("Deletable GPU")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /restore product gpu-delete-1/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/settings/recycle-bin/products/1/restore"),
        expect.objectContaining({ method: "POST" })
      );
    });
    expect(await screen.findByText("Product restored.")).toBeInTheDocument();
    expect(screen.queryByText("Deletable GPU")).not.toBeInTheDocument();
  });

  it("does not show product delete actions for staff accounts", async () => {
    const product = {
      id: 1,
      sku: "CPU-STAFF-1",
      name: "Staff Visible CPU",
      category: "CPU",
      supplier_id: null,
      cost_price: "3200.00",
      sell_price: "4500.00",
      reorder_min_qty: 1,
      reorder_multiple: 1,
      safety_stock: 10,
      active: true,
      on_hand_qty: 19,
      created_at: "2026-04-09T00:00:00Z",
      updated_at: "2026-04-09T00:00:00Z"
    };

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        return {
          ok: true,
          json: async () =>
            url.includes("/auth/me")
              ? { authenticated: true, configured: true, username: "staff", display_name: "Staff Member", role: "staff" }
              : url.includes("/products")
                ? [product]
                : []
        };
      })
    );

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /inventory/i }));
    expect(await screen.findByText("Staff Visible CPU")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /edit product cpu-staff-1/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete product cpu-staff-1/i })).not.toBeInTheDocument();
  });

  it("loads the item forecast with a 365-day history window", async () => {
    const lowStockRows = [
      {
        product_id: 1,
        sku: "SKU-LOW-1",
        name: "Low Stock Item",
        on_hand_qty: 4,
        reorder_threshold: 10
      }
    ];

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.includes("/auth/me")) {
        return {
          ok: true,
          json: async () => ({ authenticated: true, configured: true, username: "admin", display_name: "Admin User", role: "admin" })
        };
      }

      if (url.includes("/dashboard/low-stock")) {
        return {
          ok: true,
          json: async () => lowStockRows
        };
      }

      if (url.includes("/dashboard/item-forecast/1")) {
        const parsedUrl = new URL(url);
        const historyDays = Number(parsedUrl.searchParams.get("history_days") ?? "365");

        return {
          ok: true,
          json: async () => buildItemForecastDetail(historyDays)
        };
      }

      return {
        ok: true,
        json: async () => []
      };
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByText("Low Stock Item"));

    const historyWindowMetric = await screen.findByText("Sales history period");
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/dashboard/item-forecast/1?history_days=365"))).toBe(true);
    });
    expect(historyWindowMetric.closest("article")).toHaveTextContent("365 days");
    expect(screen.queryByLabelText("History range")).not.toBeInTheDocument();
  });

  it("hides account management from regular admin settings", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        return {
          ok: true,
          json: async () =>
            url.includes("/auth/me")
              ? { authenticated: true, configured: true, username: "admin", display_name: "Admin User", role: "admin" }
              : url.includes("/settings/system")
                ? { auth_enabled: true, configured: true, active_accounts: 1, super_admin_accounts: 0, admin_accounts: 1, staff_accounts: 0, session_ttl_seconds: 86400 }
                : []
        };
      })
    );

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /settings/i }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /system/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /accounts/i })).not.toBeInTheDocument();
  });

  it("shows super admin account management with role changes and audit logs", async () => {
    const accounts = [
      {
        id: 1,
        username: "super_admin",
        display_name: "Super Admin",
        email: "super@example.com",
        role: "super_admin",
        status: "active",
        created_at: "2026-01-15T00:00:00Z",
        last_login_at: null
      },
      {
        id: 2,
        username: "staff",
        display_name: "Staff Member",
        email: "staff@example.com",
        role: "staff",
        status: "active",
        created_at: "2026-01-16T00:00:00Z",
        last_login_at: null
      }
    ];
    const auditLogs = [
      {
        id: 1,
        actor_username: "super_admin",
        action: "account.created",
        target_type: "account",
        target_id: 3,
        message: "Created admin account manager.",
        created_at: "2026-01-15T00:00:00Z"
      }
    ];

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.includes("/auth/me")) {
        return {
          ok: true,
          json: async () => ({ authenticated: true, configured: true, username: "super_admin", display_name: "Super Admin", role: "super_admin" })
        };
      }

      if (url.endsWith("/settings/accounts") && init?.method === "POST") {
        const payload = JSON.parse(String(init.body));
        accounts.push({
          id: 3,
          username: payload.username,
          display_name: payload.display_name,
          email: payload.email,
          role: payload.role,
          status: "active",
          created_at: "2026-01-16T00:00:00Z",
          last_login_at: null
        });
        return {
          ok: true,
          json: async () => accounts[2]
        };
      }

      if (url.endsWith("/settings/accounts/2/role") && init?.method === "PATCH") {
        const payload = JSON.parse(String(init.body));
        accounts[1] = {
          ...accounts[1],
          role: payload.role
        };
        return {
          ok: true,
          json: async () => accounts[1]
        };
      }

      if (url.includes("/settings/accounts")) {
        return {
          ok: true,
          json: async () => accounts
        };
      }

      if (url.includes("/settings/audit-logs")) {
        return {
          ok: true,
          json: async () => auditLogs
        };
      }

      if (url.includes("/settings/system")) {
        return {
          ok: true,
          json: async () => ({
            auth_enabled: true,
            configured: true,
            active_accounts: 2,
            super_admin_accounts: 1,
            admin_accounts: 0,
            staff_accounts: 1,
            session_ttl_seconds: 86400
          })
        };
      }

      return {
        ok: true,
        json: async () => []
      };
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /settings/i }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /system/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /accounts/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /audit logs/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /accounts/i }));
    fireEvent.click(await screen.findByRole("button", { name: /promote/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/settings/accounts/2/role"),
        expect.objectContaining({ method: "PATCH" })
      );
    });
    expect(await screen.findByText("Staff Member changed to admin.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "manager" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Manager Admin" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "manager@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "manager-password" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "admin" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/settings/accounts"),
        expect.objectContaining({ method: "POST" })
      );
    });
    expect(await screen.findByText("Manager Admin")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /audit logs/i }));
    expect(await screen.findByText("Created admin account manager.")).toBeInTheDocument();
  });

  it("hides the settings tab for staff accounts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        return {
          ok: true,
          json: async () =>
            url.includes("/auth/me")
              ? { authenticated: true, configured: true, username: "staff", display_name: "Staff Member", role: "staff" }
              : []
        };
      })
    );

    render(<App />);

    expect(await screen.findByText("Low Stock Alerts")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /settings/i })).not.toBeInTheDocument();
    expect(screen.getByText("Staff Member")).toBeInTheDocument();
  });
});
