import { useState } from "react";

import { matchesSearchQuery } from "../search";
import type { StockoutRow } from "../types";

type Props = {
  rows: StockoutRow[];
  onSelectProduct?: (productId: number) => void;
};

const FORECAST_HORIZON_DAYS = 30;

export const StockoutCard = ({ rows, onSelectProduct }: Props) => {
  const [searchQuery, setSearchQuery] = useState("");
  const today = new Date(new Date().toISOString().slice(0, 10));

  const timelineRows = [...rows]
    .map((row) => {
      const predictedDate = row.predicted_stockout_date ? new Date(`${row.predicted_stockout_date}T00:00:00`) : null;
      const daysRemaining =
        predictedDate === null ? null : Math.ceil((predictedDate.getTime() - today.getTime()) / 86400000);

      if (daysRemaining === null) {
        return {
          ...row,
          daysRemaining: null,
          level: "healthy" as const,
          countdown: "🟢 No stockout within forecast horizon",
          healthPercent: 100
        };
      }

      if (daysRemaining <= 0) {
        return {
          ...row,
          daysRemaining,
          level: "danger" as const,
          countdown: "🔴 Stockout now",
          healthPercent: 0
        };
      }

      if (daysRemaining <= 3) {
        return {
          ...row,
          daysRemaining,
          level: "warning" as const,
          countdown: `🟠 Stockout in ${daysRemaining} day${daysRemaining === 1 ? "" : "s"}`,
          healthPercent: Math.max(0, Math.min(100, Math.round((daysRemaining / FORECAST_HORIZON_DAYS) * 100)))
        };
      }

      if (daysRemaining <= 10) {
        return {
          ...row,
          daysRemaining,
          level: "caution" as const,
          countdown: `🟡 Stockout in ${daysRemaining} days`,
          healthPercent: Math.max(0, Math.min(100, Math.round((daysRemaining / FORECAST_HORIZON_DAYS) * 100)))
        };
      }

      return {
        ...row,
        daysRemaining,
        level: "healthy" as const,
        countdown: `🟢 Stockout in ${daysRemaining} days`,
        healthPercent: Math.max(0, Math.min(100, Math.round((daysRemaining / FORECAST_HORIZON_DAYS) * 100)))
      };
    })
    .sort((left, right) => {
      if (left.daysRemaining === null && right.daysRemaining === null) return 0;
      if (left.daysRemaining === null) return 1;
      if (right.daysRemaining === null) return -1;
      return left.daysRemaining - right.daysRemaining;
    });
  const filteredTimelineRows = timelineRows.filter((row) =>
    matchesSearchQuery(searchQuery, [
      row.sku,
      row.name,
      row.predicted_stockout_date,
      row.suggested_qty,
      row.countdown
    ])
  );

  return (
    <section className="panel panel-scroll panel-alert">
      <div className="panel-head panel-head--search">
        <h2>Predicted Stockout Timeline</h2>
        <label className="search-field">
          <span className="sr-only">Search stockout timeline</span>
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search timeline"
          />
        </label>
      </div>
      <div className="stockout-grid">
        {filteredTimelineRows.length === 0 ? (
          <p className="empty">
            {timelineRows.length === 0 ? "No forecast-based stockout risk detected." : "No stockout rows match your search."}
          </p>
        ) : (
          filteredTimelineRows.map((row) => (
            <details className={`stockout-item stockout-item--${row.level}`} key={row.product_id}>
              <summary className="stockout-summary">
                <div>
                  <p className="stockout-title">{row.name}</p>
                  <p className="stockout-countdown">{row.countdown}</p>
                </div>
                <span
                  className={
                    row.level === "danger"
                      ? "status-pill status-pill--danger"
                      : row.level === "warning"
                        ? "status-pill status-pill--warning"
                        : row.level === "caution"
                          ? "status-pill status-pill--caution"
                        : "status-pill status-pill--healthy"
                  }
                >
                  {row.sku}
                </span>
              </summary>
              <div className="stockout-body">
                <p>
                  Predicted date: <b>{row.predicted_stockout_date ?? "Not within horizon"}</b>
                </p>
                <p>
                  Suggested reorder: <b>{row.suggested_qty} units</b>
                </p>
                <div className="health-meter" aria-label="Inventory health meter">
                  <div className="health-meter-track">
                    <div
                      className={
                        row.level === "danger"
                          ? "health-meter-fill health-meter-fill--danger"
                          : row.level === "warning"
                            ? "health-meter-fill health-meter-fill--warning"
                            : row.level === "caution"
                              ? "health-meter-fill health-meter-fill--caution"
                            : "health-meter-fill health-meter-fill--healthy"
                      }
                      style={{ width: `${row.healthPercent}%` }}
                    />
                  </div>
                  <span className="health-meter-label">Inventory health {row.healthPercent}%</span>
                </div>
                {onSelectProduct ? (
                  <button
                    type="button"
                    className="inline-action-btn"
                    onClick={() => onSelectProduct(row.product_id)}
                  >
                    Open Item Forecast
                  </button>
                ) : null}
              </div>
            </details>
          ))
        )}
      </div>
    </section>
  );
};
