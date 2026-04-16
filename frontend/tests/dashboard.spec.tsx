import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("renders the transactions snapshot table with a product detail action", async () => {
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
      updated_at: "2026-04-10T00:00:00Z"
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.includes("/auth/me")) {
        return {
          ok: true,
          json: async () => ({ authenticated: true, configured: true, username: "admin", display_name: "Admin User", role: "admin" })
        };
      }

      if (url.includes("/dashboard/item-forecast/1")) {
        return {
          ok: true,
          json: async () => buildItemForecastDetail(365)
        };
      }

      if (url.includes("/products")) {
        return {
          ok: true,
          json: async () => [product]
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

    expect(await screen.findByRole("heading", { name: "Current Inventory Snapshot" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Date" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Product" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Quantity" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Unit Price" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Total" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Actions" })).toBeInTheDocument();
    expect(screen.getByText("AMD Ryzen 3 3200")).toBeInTheDocument();
    expect(screen.getByText("CPU-AMD-3300")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /view details for amd ryzen 3 3200/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/dashboard/item-forecast/1?history_days=365"))).toBe(true);
    });
    expect(await screen.findByText("Sales history period")).toBeInTheDocument();
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

  it("shows admin settings with account creation and audit logs", async () => {
    const accounts = [
      {
        id: 1,
        username: "admin",
        display_name: "Admin User",
        email: "admin@example.com",
        role: "admin",
        status: "active",
        created_at: "2026-01-15T00:00:00Z",
        last_login_at: null
      }
    ];
    const auditLogs = [
      {
        id: 1,
        actor_username: "admin",
        action: "account.created",
        target_type: "account",
        target_id: 2,
        message: "Created staff account staff.",
        created_at: "2026-01-15T00:00:00Z"
      }
    ];

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.includes("/auth/me")) {
        return {
          ok: true,
          json: async () => ({ authenticated: true, configured: true, username: "admin", display_name: "Admin User", role: "admin" })
        };
      }

      if (url.endsWith("/settings/accounts") && init?.method === "POST") {
        const payload = JSON.parse(String(init.body));
        accounts.push({
          id: 2,
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
          json: async () => ({ auth_enabled: true, active_accounts: 1, admin_accounts: 1, staff_accounts: 0 })
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
    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "staff" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Staff Member" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "staff@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "staff-password" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "staff" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/settings/accounts"),
        expect.objectContaining({ method: "POST" })
      );
    });
    expect(await screen.findByText("Staff Member")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /audit logs/i }));
    expect(await screen.findByText("Created staff account staff.")).toBeInTheDocument();
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
