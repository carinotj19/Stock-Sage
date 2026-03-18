import type { SalesTrendPoint } from "../types";

type Props = {
  points: SalesTrendPoint[];
};

const DAILY_TARGET = 30000;
const CHART_WIDTH = 760;
const CHART_HEIGHT = 260;
const PADDING = { top: 16, right: 20, bottom: 32, left: 56 };

export const SalesTrendChart = ({ points }: Props) => {
  const formatPHP = (value: string) => {
    const numeric = Number(value);
    if (Number.isNaN(numeric)) return value;
    return new Intl.NumberFormat("en-PH", {
      style: "currency",
      currency: "PHP",
      minimumFractionDigits: 2
    }).format(numeric);
  };

  const formatDateLabel = (dateString: string) =>
    new Intl.DateTimeFormat("en-PH", {
      month: "short",
      day: "numeric"
    }).format(new Date(`${dateString}T00:00:00`));

  const series = points.map((point) => ({
    date: point.date,
    value: Number(point.total_sales)
  }));

  const totalSales = series.reduce((total, point) => total + point.value, 0);
  const maxValue = Math.max(DAILY_TARGET, ...series.map((point) => point.value), 1);
  const plotWidth = CHART_WIDTH - PADDING.left - PADDING.right;
  const plotHeight = CHART_HEIGHT - PADDING.top - PADDING.bottom;
  const stepX = series.length <= 1 ? 0 : plotWidth / (series.length - 1);

  const getX = (index: number) => PADDING.left + (series.length <= 1 ? plotWidth / 2 : index * stepX);
  const getY = (value: number) => PADDING.top + (1 - value / maxValue) * plotHeight;

  const linePoints = series.map((point, index) => `${getX(index)},${getY(point.value)}`).join(" ");
  const areaPath =
    series.length === 0
      ? ""
      : `M ${getX(0)} ${getY(series[0].value)} L ${series
          .map((point, index) => `${getX(index)} ${getY(point.value)}`)
          .join(" L ")} L ${getX(series.length - 1)} ${PADDING.top + plotHeight} L ${getX(0)} ${PADDING.top + plotHeight} Z`;
  const targetY = getY(DAILY_TARGET);

  return (
    <section className="panel panel-trend">
      <div className="panel-head">
        <h2>Sales Trend</h2>
        <div className="trend-meta">
          <span>Daily target: {formatPHP(String(DAILY_TARGET))}</span>
          <span>30-day total: {formatPHP(String(totalSales))}</span>
        </div>
      </div>
      {points.length === 0 ? (
        <p className="empty">No sales data in selected range.</p>
      ) : (
        <div className="trend-chart-wrap">
          <svg className="trend-svg" viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} role="img" aria-label="Sales trend line chart">
            {[0, 0.25, 0.5, 0.75, 1].map((step) => {
              const y = PADDING.top + plotHeight * step;
              const value = Math.round(maxValue * (1 - step));
              return (
                <g key={step}>
                  <line className="trend-grid-line" x1={PADDING.left} y1={y} x2={CHART_WIDTH - PADDING.right} y2={y} />
                  <text className="trend-grid-label" x={8} y={y + 4}>
                    {formatPHP(String(value))}
                  </text>
                </g>
              );
            })}

            <line
              className="trend-target-line"
              x1={PADDING.left}
              y1={targetY}
              x2={CHART_WIDTH - PADDING.right}
              y2={targetY}
            />

            <path className="trend-area" d={areaPath} />
            <polyline className="trend-line" points={linePoints} />

            {series.map((point, index) => (
              <circle className="trend-dot" cx={getX(index)} cy={getY(point.value)} key={point.date} r={4} />
            ))}
          </svg>

          <div className="trend-axis">
            <span>{formatDateLabel(series[0].date)}</span>
            <span>{formatDateLabel(series[series.length - 1].date)}</span>
          </div>
        </div>
      )}
    </section>
  );
};
