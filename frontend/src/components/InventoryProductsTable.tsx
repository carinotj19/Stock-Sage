import type { ProductRow } from "../types";

type InventoryProductsTableProps = {
  onSelectProduct?: (productId: number) => void;
  products: ProductRow[];
};

const formatDate = (value: string) => {
  const dateOnly = value.split("T")[0];
  const [year, month, day] = dateOnly.split("-").map(Number);

  if (!year || !month || !day) return value;

  return `${month}/${day}/${year}`;
};

const formatPHP = (value: number | string) => {
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return String(value);

  return new Intl.NumberFormat("en-PH", {
    style: "currency",
    currency: "PHP",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  }).format(numeric);
};

const getInventoryValue = (product: ProductRow) => {
  const unitPrice = Number(product.sell_price);
  if (Number.isNaN(unitPrice)) return product.sell_price;
  return product.on_hand_qty * unitPrice;
};

export const InventoryProductsTable = ({ onSelectProduct, products }: InventoryProductsTableProps) => {
  const hasProductDetail = typeof onSelectProduct === "function";

  return (
    <section className="panel panel-wide inventory-card inventory-card--products">
      <h2>Products</h2>
      <div className="table-wrap inventory-products-table-wrap">
        <table className="inventory-products-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Product</th>
              <th>Quantity</th>
              <th className="align-right">Unit Price</th>
              <th className="align-right">Total</th>
              <th className="inventory-actions-heading">Actions</th>
            </tr>
          </thead>
          <tbody>
            {products.length === 0 ? (
              <tr>
                <td colSpan={6}>No products yet.</td>
              </tr>
            ) : (
              products.map((product) => (
                <tr key={product.id}>
                  <td>{formatDate(product.created_at)}</td>
                  <td>
                    <span className="inventory-product-name">{product.name}</span>
                    <span className="inventory-product-sku">{product.sku}</span>
                  </td>
                  <td>{product.on_hand_qty}</td>
                  <td className="align-right">{formatPHP(product.sell_price)}</td>
                  <td className="align-right inventory-total-value">{formatPHP(getInventoryValue(product))}</td>
                  <td className="inventory-actions-cell">
                    {hasProductDetail ? (
                      <button
                        aria-label={`View details for ${product.sku}`}
                        className="icon-action-btn"
                        onClick={() => onSelectProduct(product.id)}
                        title="View product forecast and pricing detail"
                        type="button"
                      >
                        <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24">
                          <path d="M12 5.5c-4.2 0-7.6 2.4-9.4 6.5 1.8 4.1 5.2 6.5 9.4 6.5s7.6-2.4 9.4-6.5c-1.8-4.1-5.2-6.5-9.4-6.5Zm0 11c-2.5 0-4.5-2-4.5-4.5s2-4.5 4.5-4.5 4.5 2 4.5 4.5-2 4.5-4.5 4.5Zm0-1.8A2.7 2.7 0 1 0 12 9.3a2.7 2.7 0 0 0 0 5.4Z" />
                        </svg>
                      </button>
                    ) : (
                      <span className="muted">-</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};
