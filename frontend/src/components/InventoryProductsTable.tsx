import { useMemo, useState } from "react";

import type { ProductRow } from "../types";

type DateSortDirection = "desc" | "asc";

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

const getProductDateTimestamp = (product: ProductRow) => {
  const timestamp = Date.parse(product.created_at);
  return Number.isNaN(timestamp) ? 0 : timestamp;
};

const sortProductsByDate = (products: ProductRow[], direction: DateSortDirection) =>
  [...products].sort((left, right) => {
    const dateDiff = getProductDateTimestamp(right) - getProductDateTimestamp(left);
    const idDiff = right.id - left.id;
    const newestFirstDiff = dateDiff || idDiff;

    return direction === "desc" ? newestFirstDiff : -newestFirstDiff;
  });

export const InventoryProductsTable = ({ onSelectProduct, products }: InventoryProductsTableProps) => {
  const [dateSortDirection, setDateSortDirection] = useState<DateSortDirection>("desc");
  const hasProductDetail = typeof onSelectProduct === "function";
  const sortedProducts = useMemo(
    () => sortProductsByDate(products, dateSortDirection),
    [dateSortDirection, products]
  );
  const isLatestFirst = dateSortDirection === "desc";

  const onToggleDateSort = () => {
    setDateSortDirection((current) => (current === "desc" ? "asc" : "desc"));
  };

  return (
    <section className="panel panel-wide inventory-card inventory-card--products">
      <h2>Products</h2>
      <div className="table-wrap inventory-products-table-wrap">
        <table className="inventory-products-table">
          <thead>
            <tr>
              <th aria-sort={isLatestFirst ? "descending" : "ascending"}>
                <button
                  aria-label={`Sort products by date, ${isLatestFirst ? "oldest first" : "latest first"}`}
                  className="date-filter-btn"
                  onClick={onToggleDateSort}
                  title="Toggle date sort"
                  type="button"
                >
                  <span>Date</span>
                  <span className="date-filter-state">{isLatestFirst ? "Latest" : "Oldest"}</span>
                  <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24">
                    <path d="M4 6.5A1.5 1.5 0 0 1 5.5 5h13a1.5 1.5 0 0 1 1.1 2.52L14 13.56V18a1.5 1.5 0 0 1-.72 1.28l-2 1.22A1.5 1.5 0 0 1 9 19.22v-5.66L4.4 7.52A1.5 1.5 0 0 1 4 6.5Zm2.4.5 4.28 5.62c.2.26.32.58.32.91v4.8l1-.61v-4.19c0-.33.12-.65.32-.91L17.6 7H6.4Z" />
                  </svg>
                </button>
              </th>
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
              sortedProducts.map((product) => (
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
