import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PriceComparisonTable } from "../src/components/PriceComparisonTable";

describe("PriceComparisonTable", () => {
  it("uses explicit store and competitor price headers", () => {
    render(
      <PriceComparisonTable
        rows={[
          {
            product_id: 1,
            sku: "CPU-AMD-3300",
            name: "AMD Ryzen 3 3200",
            store_price: "4500.00",
            cheapest_competitor_price: "4200.00",
            price_gap: "300.00",
            price_gap_pct: "7.14",
            is_above_cheapest: true
          }
        ]}
      />
    );

    expect(screen.getByRole("columnheader", { name: "Store Price" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Competitor Price" })).toBeInTheDocument();
  });
});
