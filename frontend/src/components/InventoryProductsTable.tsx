import { useMemo, useState } from "react";

import { matchesSearchQuery } from "../search";
import type { ProductRow } from "../types";

export type InventoryProductUpdatePayload = {
  sku: string;
  name: string;
  sell_price: number;
  safety_stock: number;
  on_hand_qty: number;
};

type ProductEditForm = {
  sku: string;
  name: string;
  sell_price: string;
  safety_stock: string;
  on_hand_qty: string;
};

type ProductStockFilter = "all" | "in_stock" | "low_stock" | "out_of_stock";

type InventoryProductsTableProps = {
  canDeleteProducts?: boolean;
  formatPHP: (value: string) => string;
  onDeleteProduct?: (productId: number) => Promise<void>;
  onSaveProduct: (productId: number, payload: InventoryProductUpdatePayload) => Promise<void>;
  products: ProductRow[];
};

const buildProductEditForm = (product: ProductRow): ProductEditForm => ({
  sku: product.sku,
  name: product.name,
  sell_price: product.sell_price,
  safety_stock: String(product.safety_stock),
  on_hand_qty: String(product.on_hand_qty)
});

export const InventoryProductsTable = ({
  canDeleteProducts = false,
  formatPHP,
  onDeleteProduct,
  onSaveProduct,
  products
}: InventoryProductsTableProps) => {
  const [editingProductId, setEditingProductId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<ProductEditForm | null>(null);
  const [savingProductId, setSavingProductId] = useState<number | null>(null);
  const [deletingProductId, setDeletingProductId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [stockFilter, setStockFilter] = useState<ProductStockFilter>("all");
  const categoryOptions = useMemo(
    () =>
      Array.from(new Set(products.map((product) => product.category).filter((category): category is string => Boolean(category))))
        .sort((left, right) => left.localeCompare(right)),
    [products]
  );
  const isFilterActive = searchQuery.trim() !== "" || categoryFilter !== "all" || stockFilter !== "all";
  const filteredProducts = products.filter((product) =>
    matchesSearchQuery(searchQuery, [
      product.sku,
      product.name,
      product.category,
      product.on_hand_qty,
      product.sell_price,
      product.safety_stock
    ]) &&
    (categoryFilter === "all" || product.category === categoryFilter) &&
    (stockFilter === "all" ||
      (stockFilter === "out_of_stock" && product.on_hand_qty <= 0) ||
      (stockFilter === "low_stock" && product.on_hand_qty > 0 && product.on_hand_qty <= product.safety_stock) ||
      (stockFilter === "in_stock" && product.on_hand_qty > product.safety_stock))
  );

  const onStartEdit = (product: ProductRow) => {
    setEditingProductId(product.id);
    setEditForm(buildProductEditForm(product));
  };

  const onCancelEdit = () => {
    setEditingProductId(null);
    setEditForm(null);
    setSavingProductId(null);
  };

  const onEditFieldChange = (field: keyof ProductEditForm, value: string) => {
    setEditForm((current) => (current ? { ...current, [field]: value } : current));
  };

  const onSaveEdit = async (product: ProductRow) => {
    if (!editForm) return;

    const sellPrice = Number(editForm.sell_price);
    const safetyStock = Number(editForm.safety_stock);
    const onHandQty = Number(editForm.on_hand_qty);
    const isInvalidDraft =
      editForm.sku.trim() === "" ||
      editForm.name.trim() === "" ||
      Number.isNaN(sellPrice) ||
      sellPrice < 0 ||
      Number.isNaN(safetyStock) ||
      safetyStock < 0 ||
      Number.isNaN(onHandQty) ||
      onHandQty < 0;

    if (isInvalidDraft) return;

    setSavingProductId(product.id);

    try {
      await onSaveProduct(product.id, {
        sku: editForm.sku.trim(),
        name: editForm.name.trim(),
        sell_price: sellPrice,
        safety_stock: safetyStock,
        on_hand_qty: onHandQty
      });
      onCancelEdit();
    } catch {
      setSavingProductId(null);
    }
  };

  const onDelete = async (product: ProductRow) => {
    if (!onDeleteProduct) return;

    setDeletingProductId(product.id);

    try {
      await onDeleteProduct(product.id);
    } catch {
      setDeletingProductId(null);
    }
  };

  const onClearFilters = () => {
    setSearchQuery("");
    setCategoryFilter("all");
    setStockFilter("all");
  };

  return (
    <section className="panel panel-wide inventory-card inventory-card--products">
      <div className="panel-head panel-head--search">
        <h2>Products</h2>
        <label className="search-field">
          <span className="sr-only">Search products</span>
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search products"
          />
        </label>
      </div>
      <div className="table-filter-bar" aria-label="Product table filters">
        <label className="table-filter-field">
          Filter products by category
          <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
            <option value="all">All categories</option>
            {categoryOptions.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
        </label>
        <label className="table-filter-field">
          Filter products by stock status
          <select
            value={stockFilter}
            onChange={(event) => setStockFilter(event.target.value as ProductStockFilter)}
          >
            <option value="all">All stock statuses</option>
            <option value="in_stock">In stock</option>
            <option value="low_stock">Low stock</option>
            <option value="out_of_stock">Out of stock</option>
          </select>
        </label>
        <button className="secondary-btn table-filter-clear" type="button" disabled={!isFilterActive} onClick={onClearFilters}>
          Clear filters
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>SKU</th>
              <th>Name</th>
              <th>Category</th>
              <th>On Hand</th>
              <th>Sell Price</th>
              <th>Safety Stock</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredProducts.length === 0 ? (
              <tr>
                <td colSpan={7}>{products.length === 0 ? "No products yet." : "No products match your filters."}</td>
              </tr>
            ) : (
              filteredProducts.map((product) => {
                const isEditing = editingProductId === product.id && editForm !== null;
                const isSaving = savingProductId === product.id;
                const isDeleting = deletingProductId === product.id;
                const rowLabel = product.sku;

                return (
                  <tr key={product.id}>
                    <td>
                      {isEditing ? (
                        <input
                          aria-label={`SKU for ${rowLabel}`}
                          className="table-input"
                          value={editForm.sku}
                          onChange={(event) => onEditFieldChange("sku", event.target.value)}
                        />
                      ) : (
                        product.sku
                      )}
                    </td>
                    <td>
                      {isEditing ? (
                        <input
                          aria-label={`Name for ${rowLabel}`}
                          className="table-input"
                          value={editForm.name}
                          onChange={(event) => onEditFieldChange("name", event.target.value)}
                        />
                      ) : (
                        product.name
                      )}
                    </td>
                    <td>{product.category ?? "-"}</td>
                    <td>
                      {isEditing ? (
                        <input
                          aria-label={`On hand for ${rowLabel}`}
                          className="table-input"
                          min={0}
                          step={1}
                          type="number"
                          value={editForm.on_hand_qty}
                          onChange={(event) => onEditFieldChange("on_hand_qty", event.target.value)}
                        />
                      ) : (
                        product.on_hand_qty
                      )}
                    </td>
                    <td>
                      {isEditing ? (
                        <input
                          aria-label={`Sell price for ${rowLabel}`}
                          className="table-input"
                          min={0}
                          step="0.01"
                          type="number"
                          value={editForm.sell_price}
                          onChange={(event) => onEditFieldChange("sell_price", event.target.value)}
                        />
                      ) : (
                        formatPHP(product.sell_price)
                      )}
                    </td>
                    <td>
                      {isEditing ? (
                        <input
                          aria-label={`Safety stock for ${rowLabel}`}
                          className="table-input"
                          min={0}
                          step={1}
                          type="number"
                          value={editForm.safety_stock}
                          onChange={(event) => onEditFieldChange("safety_stock", event.target.value)}
                        />
                      ) : (
                        product.safety_stock
                      )}
                    </td>
                    <td>
                      {isEditing ? (
                        <div className="table-action-group">
                          <button
                            aria-label={`Save product ${rowLabel}`}
                            className="primary-btn table-action-btn"
                            disabled={isSaving}
                            onClick={() => void onSaveEdit(product)}
                            type="button"
                          >
                            {isSaving ? "Saving..." : "Save"}
                          </button>
                          <button
                            aria-label={`Cancel editing ${rowLabel}`}
                            className="secondary-btn table-action-btn"
                            disabled={isSaving}
                            onClick={onCancelEdit}
                            type="button"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <div className="table-action-group">
                          <button
                            aria-label={`Edit product ${rowLabel}`}
                            className="inline-action-btn"
                            disabled={isDeleting}
                            onClick={() => onStartEdit(product)}
                            type="button"
                          >
                            Edit
                          </button>
                          {canDeleteProducts ? (
                            <button
                              aria-label={`Delete product ${rowLabel}`}
                              className="danger-link table-danger-btn"
                              disabled={isDeleting}
                              onClick={() => void onDelete(product)}
                              type="button"
                            >
                              {isDeleting ? "Deleting..." : "Delete"}
                            </button>
                          ) : null}
                        </div>
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
