import { useState } from "react";

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

  return (
    <section className="panel panel-wide inventory-card inventory-card--products">
      <h2>Products</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>SKU</th>
              <th>Name</th>
              <th>On Hand</th>
              <th>Sell Price</th>
              <th>Safety Stock</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {products.length === 0 ? (
              <tr>
                <td colSpan={6}>No products yet.</td>
              </tr>
            ) : (
              products.map((product) => {
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
