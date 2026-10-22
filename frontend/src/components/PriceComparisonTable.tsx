import type { PriceComparisonRow } from "../types";

type Props = {
  rows: PriceComparisonRow[];
  onSelectProduct?: (productId: number) => void;
};

export const PriceComparisonTable = ({ rows, onSelectProduct }: Props) => {
  const isInteractive = typeof onSelectProduct === "function";

  const toNumber = (value: string | null) => {
    if (value === null) return null;
    const numeric = Number(value);
    return Number.isNaN(numeric) ? null : numeric;
  };

  const formatPHP = (value: string | null) => {
    if (value === null) return "-";
    const numeric = Number(value);
    if (Number.isNaN(numeric)) return value;
    return new Intl.NumberFormat("en-PH", {
      style: "currency",
      currency: "PHP",
      minimumFractionDigits: 2
    }).format(numeric);
  };

  return (
    <section className="panel panel-scroll panel-compare">
      <h2>Price Comparison Results</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>SKU</th>
              <th className="align-right">Store Price</th>
              <th className="align-right">Competitor Price</th>
              <th>Difference</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4}>No competitor snapshots available.</td>
              </tr>
            ) : (
              rows.map((row) => {
                const competitorPrice = toNumber(row.cheapest_competitor_price);
                const gapValue = Math.abs(toNumber(row.price_gap) ?? 0);
                const signedDiff = competitorPrice === null ? null : row.is_above_cheapest ? -gapValue : gapValue;

                return (
                  <tr
                    className={isInteractive ? "price-compare-row price-compare-row--interactive" : "price-compare-row"}
                    key={row.product_id}
                    onClick={isInteractive ? () => onSelectProduct(row.product_id) : undefined}
                    title={`${row.name}${isInteractive ? " (click for forecast detail)" : ""}`}
                  >
                    <td>
                      <span className="sku-value">{row.sku}</span>
                    </td>
                    <td className="align-right">{formatPHP(row.store_price)}</td>
                    <td className="align-right">{formatPHP(row.cheapest_competitor_price)}</td>
                    <td>
                      {signedDiff === null ? (
                        <span className="price-delta price-delta--neutral">-</span>
                      ) : signedDiff < 0 ? (
                        <span className="price-delta price-delta--negative">
                          🔴 -{formatPHP(String(Math.abs(signedDiff)))}
                        </span>
                      ) : (
                        <span className="price-delta price-delta--positive">🟢 +{formatPHP(String(signedDiff))}</span>
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
