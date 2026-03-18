import type { ItemForecastDetail } from "../types";

type Props = {
  isOpen: boolean;
  item: ItemForecastDetail | null;
  isLoading: boolean;
  error: string | null;
  onClose: () => void;
};

const CHART_WIDTH = 760;
const CHART_HEIGHT = 250;
const PADDING = { top: 18, right: 18, bottom: 32, left: 46 };

const toNumber = (value: string | null) => {
  if (value === null) return null;
  const numeric = Number(value);
  return Number.isNaN(numeric) ? null : numeric;
};

const toPath = (points: Array<{ x: number; y: number }>) => {
  if (points.length === 0) return "";
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
};

const formatPHP = (value: number | string | null) => {
  if (value === null) return "-";
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(numeric)) return String(value);
  return new Intl.NumberFormat("en-PH", {
    style: "currency",
    currency: "PHP",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  }).format(numeric);
};

const formatDate = (value: string) =>
  new Intl.DateTimeFormat("en-PH", {
    month: "short",
    day: "numeric"
  }).format(new Date(`${value}T00:00:00`));

export const ForecastItemModal = ({ isOpen, item, isLoading, error, onClose }: Props) => {
  if (!isOpen) return null;

  if (isLoading || error || !item) {
    return (
      <div className="modal-overlay" role="presentation" onClick={onClose}>
        <section className="modal-card modal-card--state" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close forecast detail">
            x
          </button>
          <header className="modal-header">
            <h2>Item Forecast</h2>
            <p className="meta">Per-item demand and reorder projection</p>
          </header>
          <div className={error ? "modal-state modal-state--error" : "modal-state"}>
            {isLoading ? "Loading forecast details..." : error ?? "No forecast detail found for this item."}
          </div>
        </section>
      </div>
    );
  }

  const points = [...item.demand_points].sort((left, right) => left.date.localeCompare(right.date));
  const maxUnits = Math.max(1, ...points.map((point) => point.units));
  const plotWidth = CHART_WIDTH - PADDING.left - PADDING.right;
  const plotHeight = CHART_HEIGHT - PADDING.top - PADDING.bottom;
  const stepX = points.length <= 1 ? 0 : plotWidth / (points.length - 1);
  const getX = (index: number) => PADDING.left + (points.length <= 1 ? plotWidth / 2 : index * stepX);
  const getY = (units: number) => PADDING.top + (1 - units / maxUnits) * plotHeight;

  const chartPoints = points.map((point, index) => ({ x: getX(index), y: getY(point.units), ...point }));
  const historyChartPoints = chartPoints.filter((point) => point.kind === "history");
  const forecastChartPoints = chartPoints.filter((point) => point.kind === "forecast");
  const forecastPathPoints =
    historyChartPoints.length > 0 && forecastChartPoints.length > 0
      ? [historyChartPoints[historyChartPoints.length - 1], ...forecastChartPoints]
      : forecastChartPoints;

  const storePrice = toNumber(item.price_analysis.store_price);
  const marketAvg = toNumber(item.price_analysis.market_avg_price);
  const differencePct = toNumber(item.price_analysis.difference_pct);
  const confidenceDisplay = item.confidence_pct === null ? "n/a" : `${item.confidence_pct.toFixed(0)}%`;
  const stockoutLabel =
    item.predicted_stockout_date === null
      ? "No stockout in horizon"
      : `${item.predicted_stockout_date} (${item.days_until_stockout ?? 0} days)`;

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <section className="modal-card" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close-btn" onClick={onClose} aria-label="Close forecast detail">
          x
        </button>

        <header className="modal-header">
          <h2>{item.name}</h2>
          <p className="meta">{item.sku}</p>
        </header>

        <section className="modal-metrics-grid">
          <article className="modal-metric">
            <p className="kpi-label">Predicted/mo</p>
            <p className="kpi-value">{item.predicted_per_month.toFixed(0)}</p>
          </article>
          <article className="modal-metric">
            <p className="kpi-label">In Stock</p>
            <p className="kpi-value">{item.in_stock}</p>
          </article>
          <article className="modal-metric">
            <p className="kpi-label">Reorder Qty</p>
            <p className="kpi-value">{item.reorder_qty}</p>
          </article>
          <article className="modal-metric">
            <p className="kpi-label">Confidence</p>
            <p className="kpi-value">{confidenceDisplay}</p>
          </article>
        </section>

        <section className="modal-section">
          <div className="panel-head">
            <h3>Demand Forecast</h3>
            <p className="meta">Stockout: {stockoutLabel}</p>
          </div>
          <svg className="modal-chart" viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} role="img" aria-label="Demand chart">
            {[0, 0.25, 0.5, 0.75, 1].map((step) => {
              const y = PADDING.top + plotHeight * step;
              const value = Math.round(maxUnits * (1 - step));
              return (
                <g key={step}>
                  <line className="trend-grid-line" x1={PADDING.left} y1={y} x2={CHART_WIDTH - PADDING.right} y2={y} />
                  <text className="trend-grid-label" x={8} y={y + 4}>
                    {value}
                  </text>
                </g>
              );
            })}

            <path className="modal-history-line" d={toPath(historyChartPoints)} />
            <path className="modal-forecast-line" d={toPath(forecastPathPoints)} />

            {historyChartPoints.map((point) => (
              <circle className="modal-history-dot" key={`h-${point.date}`} cx={point.x} cy={point.y} r={3.5} />
            ))}
            {forecastChartPoints.map((point) => (
              <circle className="modal-forecast-dot" key={`f-${point.date}`} cx={point.x} cy={point.y} r={3.5} />
            ))}
          </svg>
          <div className="modal-chart-axis">
            <span>{points[0] ? formatDate(points[0].date) : "-"}</span>
            <span>{points[points.length - 1] ? formatDate(points[points.length - 1].date) : "-"}</span>
          </div>
        </section>

        <section className="modal-section modal-warning">
          <h3>When To Buy</h3>
          <p>{item.when_to_buy_message}</p>
        </section>

        <section className="modal-section">
          <h3>Price Analysis</h3>
          <div className="modal-price-grid">
            <article>
              <p className="kpi-label">Your Price</p>
              <p className="kpi-value">{formatPHP(storePrice)}</p>
            </article>
            <article>
              <p className="kpi-label">Market Avg</p>
              <p className="kpi-value">{formatPHP(marketAvg)}</p>
            </article>
            <article>
              <p className="kpi-label">Difference</p>
              <p className={differencePct !== null && differencePct > 0 ? "kpi-value kpi-value--warn" : "kpi-value"}>
                {differencePct === null ? "n/a" : `${differencePct > 0 ? "+" : ""}${differencePct.toFixed(2)}%`}
              </p>
            </article>
          </div>
          {item.price_analysis.suggested_price ? (
            <p className="meta">
              Suggested price target: <b>{formatPHP(item.price_analysis.suggested_price)}</b>
            </p>
          ) : null}
          {item.price_analysis.competitor_benchmarks.length > 0 ? (
            <div className="chip-row">
              {item.price_analysis.competitor_benchmarks.map((benchmark) => (
                <span className="chip" key={benchmark.source_name}>
                  {benchmark.source_name}: {formatPHP(benchmark.price)}
                </span>
              ))}
            </div>
          ) : (
            <p className="meta">No competitor snapshots for this item yet.</p>
          )}
        </section>
      </section>
    </div>
  );
};
