import { describe, expect, it } from "vitest";

import { demoRequestJson } from "../src/demoApi";
import type { ItemForecastDetail, ProductRow, SaleTransactionPage } from "../src/types";

describe("public demo API", () => {
  it("provides a local authenticated viewer without a backend", async () => {
    const auth = await demoRequestJson<{
      authenticated: boolean;
      configured: boolean;
      username: string | null;
      display_name: string | null;
      role: string | null;
    }>("/auth/me");

    expect(auth).toMatchObject({
      authenticated: true,
      configured: true,
      username: "demo",
      display_name: "Demo Viewer",
      role: "staff"
    });
  });

  it("serves representative inventory, transaction, and forecast data", async () => {
    const products = await demoRequestJson<ProductRow[]>("/products");
    const sales = await demoRequestJson<SaleTransactionPage>("/sales?page=1&page_size=50&sort=desc");
    const forecast = await demoRequestJson<ItemForecastDetail>(
      `/dashboard/item-forecast/${products[0].id}?history_days=365`
    );

    expect(products.length).toBeGreaterThanOrEqual(5);
    expect(sales.items.length).toBeGreaterThan(0);
    expect(forecast.product_id).toBe(products[0].id);
    expect(forecast.demand_points.some((point) => point.kind === "forecast")).toBe(true);
  });

  it("keeps the public demo read-only", async () => {
    await expect(
      demoRequestJson("/products", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      })
    ).rejects.toThrow("Public demo is read-only");
  });
});
