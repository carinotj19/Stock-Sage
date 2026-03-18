import type { LowStockRow } from "../types";

type Props = {
  rows: LowStockRow[];
  onSelectProduct?: (productId: number) => void;
};

export const LowStockTable = ({ rows, onSelectProduct }: Props) => {
  const getStockPercent = (row: LowStockRow) =>
    row.reorder_threshold > 0 ? Math.max(0, Math.round((row.on_hand_qty / row.reorder_threshold) * 100)) : 100;

  const getSeverity = (row: LowStockRow) => {
    const percent = getStockPercent(row);
    if (row.on_hand_qty <= 0) return "out";
    if (percent <= 30) return "critical";
    return "low";
  };

  const sortedRows = [...rows].sort((left, right) => {
    const percentDiff = getStockPercent(left) - getStockPercent(right);
    if (percentDiff !== 0) return percentDiff;
    return left.on_hand_qty - right.on_hand_qty;
  });

  return (
    <section className="panel panel-scroll panel-alert">
      <h2>Low Stock Alerts</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>SKU</th>
              <th>Product</th>
              <th>Stock</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.length === 0 ? (
              <tr>
                <td colSpan={4}>
                  <span className="status-pill status-pill--healthy">🟢 Healthy stock across tracked SKUs</span>
                </td>
              </tr>
            ) : (
              sortedRows.map((row) => {
                const stockPercent = getStockPercent(row);
                const severity = getSeverity(row);
                const isInteractive = typeof onSelectProduct === "function";
                return (
                <tr
                  className={`stock-row stock-row--${severity}${isInteractive ? " stock-row--interactive" : ""}`}
                  key={row.product_id}
                  title={`${row.name} reorder threshold: ${row.reorder_threshold}${isInteractive ? " (click for forecast detail)" : ""}`}
                  onClick={isInteractive ? () => onSelectProduct(row.product_id) : undefined}
                  onKeyDown={
                    isInteractive
                      ? (event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onSelectProduct(row.product_id);
                          }
                        }
                      : undefined
                  }
                  tabIndex={isInteractive ? 0 : undefined}
                  role={isInteractive ? "button" : undefined}
                >
                  <td>{row.sku}</td>
                  <td>{row.name}</td>
                  <td>
                    <strong>{row.on_hand_qty}</strong>
                    <span className="muted"> / {row.reorder_threshold}</span>
                    <span className="stock-percent">{stockPercent}%</span>
                  </td>
                  <td>
                    {severity === "out" ? (
                      <span className="status-pill status-pill--danger">🔴 Out of stock</span>
                    ) : severity === "critical" ? (
                      <span className="status-pill status-pill--critical">🟠 Critical</span>
                    ) : (
                      <span className="status-pill status-pill--warning">🟠 Low stock</span>
                    )}
                  </td>
                </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};
