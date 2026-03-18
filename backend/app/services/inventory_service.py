from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import StockMovement, Supplier
from app.repositories.product_repository import ProductRepository
from app.schemas.inventory import (
    InventoryAdjustRequest,
    InventoryAdjustResponse,
    ProductCreate,
    ProductRead,
    SupplierCreate,
)


class InventoryService:
    def __init__(self, db: Session, product_repository: ProductRepository | None = None) -> None:
        self.db = db
        self.product_repository = product_repository or ProductRepository()

    def create_supplier(self, payload: SupplierCreate) -> Supplier:
        supplier = Supplier(
            name=payload.name,
            contact_name=payload.contact_name,
            phone=payload.phone,
            email=payload.email,
            lead_time_days_default=payload.lead_time_days_default,
        )
        self.db.add(supplier)

        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Supplier with name '{payload.name}' already exists.",
            ) from exc

        self.db.refresh(supplier)
        return supplier

    def create_product(self, payload: ProductCreate) -> ProductRead:
        if payload.supplier_id is not None:
            supplier = self.db.get(Supplier, payload.supplier_id)
            if supplier is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Supplier {payload.supplier_id} was not found.",
                )

        product = self.product_repository.create_product(self.db, payload)
        balance = self.product_repository.create_inventory_balance(
            self.db, product_id=product.id, on_hand_qty=payload.initial_stock
        )

        if payload.initial_stock:
            movement = StockMovement(
                product_id=product.id,
                movement_type="adjustment",
                qty_delta=payload.initial_stock,
                reason="initial_stock",
                occurred_at=datetime.now(timezone.utc),
            )
            self.db.add(movement)

        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Product with SKU '{payload.sku}' already exists.",
            ) from exc

        self.db.refresh(product)
        self.db.refresh(balance)
        return self._to_product_read(product.id)

    def list_products(self) -> list[ProductRead]:
        products = self.product_repository.list_products(self.db)
        result: list[ProductRead] = []

        for product in products:
            balance = self.product_repository.get_inventory_balance(self.db, product.id)
            result.append(
                ProductRead(
                    id=product.id,
                    sku=product.sku,
                    name=product.name,
                    category=product.category,
                    supplier_id=product.supplier_id,
                    cost_price=product.cost_price,
                    sell_price=product.sell_price,
                    reorder_min_qty=product.reorder_min_qty,
                    reorder_multiple=product.reorder_multiple,
                    safety_stock=product.safety_stock,
                    active=product.active,
                    on_hand_qty=balance.on_hand_qty if balance else 0,
                    created_at=product.created_at,
                    updated_at=product.updated_at,
                )
            )

        return result

    def adjust_stock(self, payload: InventoryAdjustRequest) -> InventoryAdjustResponse:
        product = self.product_repository.get_product(self.db, payload.product_id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {payload.product_id} was not found.",
            )

        balance = self.product_repository.get_inventory_balance(self.db, payload.product_id)
        if balance is None:
            balance = self.product_repository.create_inventory_balance(self.db, payload.product_id, on_hand_qty=0)

        next_qty = balance.on_hand_qty + payload.qty_delta
        if next_qty < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient stock for requested adjustment.",
            )

        timestamp = datetime.now(timezone.utc)
        balance.on_hand_qty = next_qty
        balance.last_movement_at = timestamp

        movement = StockMovement(
            product_id=payload.product_id,
            movement_type="adjustment",
            qty_delta=payload.qty_delta,
            unit_price=payload.unit_price,
            reason=payload.reason,
            reference_type=payload.reference_type,
            reference_id=payload.reference_id,
            occurred_at=timestamp,
        )
        self.db.add(movement)
        self.db.commit()
        self.db.refresh(balance)

        return InventoryAdjustResponse(
            product_id=payload.product_id,
            on_hand_qty=balance.on_hand_qty,
            last_movement_at=balance.last_movement_at,
        )

    def _to_product_read(self, product_id: int) -> ProductRead:
        product = self.product_repository.get_product(self.db, product_id)
        balance = self.product_repository.get_inventory_balance(self.db, product_id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {product_id} was not found.",
            )

        return ProductRead(
            id=product.id,
            sku=product.sku,
            name=product.name,
            category=product.category,
            supplier_id=product.supplier_id,
            cost_price=product.cost_price,
            sell_price=product.sell_price,
            reorder_min_qty=product.reorder_min_qty,
            reorder_multiple=product.reorder_multiple,
            safety_stock=product.safety_stock,
            active=product.active,
            on_hand_qty=balance.on_hand_qty if balance else 0,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )

