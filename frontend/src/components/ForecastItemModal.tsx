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
const DENSE_HISTORY_THRESHOLD = 120;
const HISTORY_DOT_THRESHOLD = 90;
const DENSE_AXIS_TICK_COUNT = 5;
const DEFAULT_AXIS_TICK_COUNT = 2;

const toNumber = (value: string | null) => {
  if (value === null) return null;
  const numeric = Number(value);
  return Number.isNaN(numeric) ? null : numeric;
};

const toPath = (points: Array<{ x: number; y: number }>) => {
  if (points.length === 0) return "";
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
};

const toMovingAverage = (values: number[], windowSize: number) =>
  values.map((_, index) => {
    const start = Math.max(0, index - windowSize + 1);
    const window = values.slice(start, index + 1);
    return window.reduce((total, value) => total + value, 0) / window.length;
  });

const toTickIndices = (pointsLength: number, tickCount: number) => {
  if (pointsLength <= 0) return [];
  if (pointsLength === 1 || tickCount <= 1) return [0];
  if (tickCount === 2) return [0, pointsLength - 1];

  return Array.from(
    new Set(
      Array.from({ length: tickCount }, (_, index) => Math.round(((pointsLength - 1) * index) / (tickCount - 1)))
    )
  );
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

const formatUnits = (value: number, fractionDigits = 0) => value.toFixed(fractionDigits);

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
  const trendChartPoints = toMovingAverage(points.map((point) => point.units), 7).map((units, index) => ({
    x: getX(index),
    y: getY(units)
  }));
  const forecastPathPoints =
    historyChartPoints.length > 0 && forecastChartPoints.length > 0
      ? [historyChartPoints[historyChartPoints.length - 1], ...forecastChartPoints]
      : forecastChartPoints;
  const historyTotalUnits = historyChartPoints.reduce((total, point) => total + point.units, 0);
  const forecastTotalUnits = forecastChartPoints.reduce((total, point) => total + point.units, 0);
  const historyAverageUnits = historyChartPoints.length === 0 ? 0 : historyTotalUnits / historyChartPoints.length;
  const forecastAverageUnits = forecastChartPoints.length === 0 ? 0 : forecastTotalUnits / forecastChartPoints.length;
  const peakForecastUnits = forecastChartPoints.length === 0 ? 0 : Math.max(...forecastChartPoints.map((point) => point.units));
  const forecastAverageY = getY(forecastAverageUnits);
  const historyStartPoint = historyChartPoints[0];
  const historyEndPoint = historyChartPoints[historyChartPoints.length - 1];
  const forecastStartPoint = forecastChartPoints[0];
  const forecastEndPoint = forecastChartPoints[forecastChartPoints.length - 1];
  const forecastDividerX = forecastStartPoint?.x ?? null;
  const showHistoryDots = historyChartPoints.length <= HISTORY_DOT_THRESHOLD;
  const axisTickIndices = toTickIndices(
    points.length,
    points.length > DENSE_HISTORY_THRESHOLD ? DENSE_AXIS_TICK_COUNT : DEFAULT_AXIS_TICK_COUNT
  );
  const historyLineClassName =
    historyChartPoints.length > DENSE_HISTORY_THRESHOLD ? "modal-history-line modal-history-line--dense" : "modal-history-line";

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
            <div>
              <h3>Demand Forecast</h3>
              <p className="meta">Green shows actual daily sales, orange shows the 7-day trend, and blue shows the forecast.</p>
            </div>
            <div className="modal-stockout-chip">
              <span className="kpi-label">Stockout</span>
              <span className="kpi-value">{stockoutLabel}</span>
            </div>
          </div>
          <div className="modal-demand-grid">
            <article className="modal-demand-metric">
              <p className="kpi-label">Sales history period</p>
              <p className="kpi-value">{historyChartPoints.length} days</p>
              <p className="modal-demand-helper">
                {historyStartPoint && historyEndPoint ? `${formatDate(historyStartPoint.date)} to ${formatDate(historyEndPoint.date)}` : "No sales history"}
              </p>
            </article>
            <article className="modal-demand-metric">
              <p className="kpi-label">Units sold in history</p>
              <p className="kpi-value">{formatUnits(historyTotalUnits)}</p>
              <p className="modal-demand-helper">Total units sold across the history period</p>
            </article>
            <article className="modal-demand-metric">
              <p className="kpi-label">Average sold/day</p>
              <p className="kpi-value">{formatUnits(historyAverageUnits, 2)}</p>
              <p className="modal-demand-helper">Average daily units sold in the history period</p>
            </article>
            <article className="modal-demand-metric">
              <p className="kpi-label">Forecast horizon</p>
              <p className="kpi-value">{forecastChartPoints.length} days</p>
              <p className="modal-demand-helper">
                {forecastStartPoint && forecastEndPoint ? `${formatDate(forecastStartPoint.date)} to ${formatDate(forecastEndPoint.date)}` : "No forecast"}
              </p>
            </article>
            <article className="modal-demand-metric">
              <p className="kpi-label">Projected units</p>
              <p className="kpi-value">{formatUnits(forecastTotalUnits)}</p>
              <p className="modal-demand-helper">Expected units during the forecast horizon</p>
            </article>
            <article className="modal-demand-metric">
              <p className="kpi-label">Projected avg/day</p>
              <p className="kpi-value">{formatUnits(forecastAverageUnits, 2)}</p>
              <p className="modal-demand-helper">Average projected daily demand</p>
            </article>
          </div>
          <div className="modal-demand-guide">
            <h4>How to read this chart</h4>
            <div className="modal-demand-guide-grid">
              <article className="modal-demand-guide-item">
                <span className="modal-demand-swatch modal-demand-swatch--history" aria-hidden="true" />
                <div>
                  <p className="modal-demand-guide-title">Actual sales</p>
                  <p className="modal-demand-guide-copy">Daily units sold. Days with no sales stay at zero.</p>
                </div>
              </article>
              <article className="modal-demand-guide-item">
                <span className="modal-demand-swatch modal-demand-swatch--trend" aria-hidden="true" />
                <div>
                  <p className="modal-demand-guide-title">Demand trend</p>
                  <p className="modal-demand-guide-copy">A 7-day moving average that smooths the sales spikes.</p>
                </div>
              </article>
              <article className="modal-demand-guide-item">
                <span className="modal-demand-swatch modal-demand-swatch--forecast" aria-hidden="true" />
                <div>
                  <p className="modal-demand-guide-title">Forecast</p>
                  <p className="modal-demand-guide-copy">Projected daily demand after the forecast start marker.</p>
                </div>
              </article>
            </div>
          </div>
          <svg
            className="modal-chart"
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            role="img"
            aria-label="Demand chart showing actual sales history, demand trend, and forecast"
          >
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

            {forecastDividerX !== null ? (
              <>
                <rect
                  className="modal-forecast-region"
                  x={forecastDividerX}
                  y={PADDING.top}
                  width={CHART_WIDTH - PADDING.right - forecastDividerX}
                  height={plotHeight}
                />
                <line
                  className="modal-forecast-divider"
                  x1={forecastDividerX}
                  y1={PADDING.top}
                  x2={forecastDividerX}
                  y2={PADDING.top + plotHeight}
                />
                <text className="modal-forecast-divider-label" x={Math.min(forecastDividerX + 8, CHART_WIDTH - PADDING.right - 92)} y={PADDING.top + 14}>
                  Forecast starts
                </text>
              </>
            ) : null}

            {forecastChartPoints.length > 0 ? (
              <line
                className="modal-forecast-average-line"
                x1={forecastChartPoints[0].x}
                y1={forecastAverageY}
                x2={forecastChartPoints[forecastChartPoints.length - 1].x}
                y2={forecastAverageY}
              />
            ) : null}

            <path className={historyLineClassName} d={toPath(historyChartPoints)} />
            <path className="modal-forecast-line" d={toPath(forecastPathPoints)} />
            <path className="modal-trend-line" d={toPath(trendChartPoints)} />

            {showHistoryDots
              ? historyChartPoints.map((point) => (
                  <circle className="modal-history-dot" key={`h-${point.date}`} cx={point.x} cy={point.y} r={3.5} />
                ))
              : null}
            {forecastChartPoints.map((point) => (
              <circle className="modal-forecast-dot" key={`f-${point.date}`} cx={point.x} cy={point.y} r={3.5} />
            ))}
          </svg>
          <div className="modal-chart-axis">
            {axisTickIndices.map((index) => (
              <span key={points[index]?.date ?? index}>{points[index] ? formatDate(points[index].date) : "-"}</span>
            ))}
          </div>
          <div className="modal-chart-summary">
            <span>
              Sales history:{" "}
              <b>{historyStartPoint && historyEndPoint ? `${formatDate(historyStartPoint.date)} to ${formatDate(historyEndPoint.date)}` : "-"}</b>
            </span>
            <span>
              Forecast:{" "}
              <b>{forecastStartPoint && forecastEndPoint ? `${formatDate(forecastStartPoint.date)} to ${formatDate(forecastEndPoint.date)}` : "-"}</b>
            </span>
            <span>
              Peak forecast: <b>{formatUnits(peakForecastUnits, 2)} units</b>
            </span>
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
