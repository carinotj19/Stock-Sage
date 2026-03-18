import type { PriceComparisonRow } from "../types";

type Props = {
  rows: PriceComparisonRow[];
  onSelectProduct?: (productId: number) => void;
};

export const PriceComparisonTable = ({ rows, onSelectProduct }: Props) => {
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
              <th className="align-right">Store</th>
              <th className="align-right">Competitor</th>
              <th>Difference</th>
              <th>Competitiveness</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5}>No competitor snapshots available.</td>
              </tr>
            ) : (
              rows.map((row) => {
                const storePrice = toNumber(row.store_price) ?? 0;
                const competitorPrice = toNumber(row.cheapest_competitor_price);
                const gapValue = Math.abs(toNumber(row.price_gap) ?? 0);
                const signedDiff = competitorPrice === null ? null : row.is_above_cheapest ? -gapValue : gapValue;
                const normalizedGap = storePrice > 0 ? Math.min(1, gapValue / storePrice) : 0;
                const competitiveness =
                  competitorPrice === null
                    ? 100
                    : row.is_above_cheapest
                      ? Math.max(0, Math.round(100 - normalizedGap * 100))
                      : Math.min(100, Math.round(85 + normalizedGap * 100));

                return (
                <tr key={row.product_id} title={row.name}>
                  <td>
                    {onSelectProduct ? (
                      <button
                        type="button"
                        className="inline-link-btn"
                        onClick={() => onSelectProduct(row.product_id)}
                      >
                        {row.sku}
                      </button>
                    ) : (
                      row.sku
                    )}
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
                  <td>
                    <div className="score-stack" title={`${competitiveness}%`}>
                      <div className="score-meter">
                        <div className="score-fill" style={{ width: `${competitiveness}%` }} />
                      </div>
                      <span className="score-label">{competitiveness}%</span>
                    </div>
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
