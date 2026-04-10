import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ForecastItemModal } from "../src/components/ForecastItemModal";

const toDateString = (baseDate: Date, offsetDays: number) => {
  const date = new Date(baseDate);
  date.setUTCDate(date.getUTCDate() + offsetDays);
  return date.toISOString().slice(0, 10);
};

describe("ForecastItemModal", () => {
  it("shows clearer demand forecast labels and legend", () => {
    const { container } = render(
      <ForecastItemModal
        isOpen={true}
        isLoading={false}
        error={null}
        onClose={() => {}}
        item={{
          product_id: 1,
          sku: "CPU-AMD-3300",
          name: "AMD Ryzen 3 3200",
          forecast_horizon_days: 3,
          predicted_per_month: 60,
          in_stock: 10,
          reorder_qty: 8,
          confidence_pct: 80,
          predicted_stockout_date: "2026-04-12",
          days_until_stockout: 2,
          when_to_buy_message: "Order 8 units now.",
          demand_points: [
            { date: "2026-04-01", units: 1, kind: "history" },
            { date: "2026-04-02", units: 3, kind: "history" },
            { date: "2026-04-03", units: 2, kind: "forecast" },
            { date: "2026-04-04", units: 4, kind: "forecast" },
            { date: "2026-04-05", units: 2, kind: "forecast" }
          ],
          price_analysis: {
            store_price: "4500.00",
            market_avg_price: "4300.00",
            difference_pct: "4.65",
            suggested_price: null,
            competitor_benchmarks: []
          }
        }}
      />
    );

    const historyWindowMetric = screen.getByText("Sales history period").closest("article");
    const historyUnitsMetric = screen.getByText("Units sold in history").closest("article");
    const forecastWindowMetric = screen.getByText("Forecast horizon").closest("article");
    const forecastUnitsMetric = screen.getByText("Projected units").closest("article");
    const averageForecastMetric = screen.getByText("Projected avg/day").closest("article");

    expect(historyWindowMetric).not.toBeNull();
    expect(historyUnitsMetric).not.toBeNull();
    expect(forecastWindowMetric).not.toBeNull();
    expect(forecastUnitsMetric).not.toBeNull();
    expect(averageForecastMetric).not.toBeNull();

    expect(within(historyWindowMetric!).getByText("2 days")).toBeInTheDocument();
    expect(within(historyUnitsMetric!).getByText("4")).toBeInTheDocument();
    expect(within(forecastWindowMetric!).getByText("3 days")).toBeInTheDocument();
    expect(within(forecastUnitsMetric!).getByText("8")).toBeInTheDocument();
    expect(within(averageForecastMetric!).getByText("2.67")).toBeInTheDocument();
    expect(screen.getByText("How to read this chart")).toBeInTheDocument();
    expect(screen.getByText("Actual sales")).toBeInTheDocument();
    expect(screen.getByText("Demand trend")).toBeInTheDocument();
    expect(screen.getByText("Forecast")).toBeInTheDocument();
    expect(screen.getByText("Forecast starts")).toBeInTheDocument();
    expect(container.querySelector(".modal-trend-line")).not.toBeNull();
    expect(container.querySelector(".modal-forecast-average-line")).not.toBeNull();
    expect(container.querySelector(".modal-forecast-divider")).not.toBeNull();
  });

  it("keeps a 365-day history chart readable", () => {
    const historyPoints = Array.from({ length: 365 }, (_, index) => ({
      date: toDateString(new Date("2025-04-01T00:00:00.000Z"), index),
      units: 2,
      kind: "history" as const
    }));
    const forecastPoints = Array.from({ length: 30 }, (_, index) => ({
      date: toDateString(new Date("2026-04-01T00:00:00.000Z"), index),
      units: 3,
      kind: "forecast" as const
    }));

    const { container } = render(
      <ForecastItemModal
        isOpen={true}
        isLoading={false}
        error={null}
        onClose={() => {}}
        item={{
          product_id: 1,
          sku: "CPU-AMD-3300",
          name: "AMD Ryzen 3 3200",
          forecast_horizon_days: 30,
          predicted_per_month: 90,
          in_stock: 10,
          reorder_qty: 8,
          confidence_pct: 80,
          predicted_stockout_date: "2026-04-30",
          days_until_stockout: 30,
          when_to_buy_message: "Order 8 units now.",
          demand_points: [...historyPoints, ...forecastPoints],
          price_analysis: {
            store_price: "4500.00",
            market_avg_price: "4300.00",
            difference_pct: "4.65",
            suggested_price: null,
            competitor_benchmarks: []
          }
        }}
      />
    );

    const historyWindowMetric = screen.getByText("Sales history period").closest("article");
    const historyUnitsMetric = screen.getByText("Units sold in history").closest("article");
    const averageHistoryMetric = screen.getByText("Average sold/day").closest("article");

    expect(historyWindowMetric).not.toBeNull();
    expect(historyUnitsMetric).not.toBeNull();
    expect(averageHistoryMetric).not.toBeNull();

    expect(within(historyWindowMetric!).getByText("365 days")).toBeInTheDocument();
    expect(within(historyUnitsMetric!).getByText("730")).toBeInTheDocument();
    expect(within(averageHistoryMetric!).getByText("2.00")).toBeInTheDocument();
    expect(container.querySelectorAll(".modal-history-dot")).toHaveLength(0);
    expect(container.querySelectorAll(".modal-chart-axis span")).toHaveLength(5);
  });
});
