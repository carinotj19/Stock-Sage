import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../src/App";


describe("Dashboard rendering", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => []
      })
    );
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
});
