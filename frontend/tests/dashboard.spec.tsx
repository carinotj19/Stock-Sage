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
              ? { authenticated: true, configured: true, username: "admin" }
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
              ? { authenticated: false, configured: true, username: null }
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
          json: async () => ({ authenticated: true, configured: true, username: "admin" })
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
          json: async () => ({ authenticated: true, configured: true, username: "admin" })
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
});
