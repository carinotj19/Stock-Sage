from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import InventoryBalance, Product, SalesItem, SalesTransaction, StockMovement
from app.schemas.sales import SaleCreate, SaleItemRead, SaleRead


class SalesService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_sale(self, payload: SaleCreate) -> SaleRead:
        timestamp = payload.sold_at or datetime.now(timezone.utc)
        receipt_no = payload.receipt_no or f"R-{uuid4().hex[:12].upper()}"

        try:
            with self.db.begin():
                transaction = SalesTransaction(
                    receipt_no=receipt_no,
                    sold_at=timestamp,
                    total_amount=Decimal("0.00"),
                    payment_method=payload.payment_method,
                )
                self.db.add(transaction)
                self.db.flush()

                total_amount = Decimal("0.00")
                sales_items: list[SalesItem] = []

                for item in payload.items:
                    product = self.db.get(Product, item.product_id)
                    if product is None:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Product {item.product_id} was not found.",
                        )

                    balance = self.db.get(InventoryBalance, item.product_id)
                    if balance is None or balance.on_hand_qty < item.qty:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Insufficient stock for product {item.product_id}.",
                        )

                    unit_price = item.unit_sell_price if item.unit_sell_price is not None else product.sell_price
                    line_total = unit_price * item.qty
                    total_amount += line_total

                    sales_item = SalesItem(
                        sales_transaction_id=transaction.id,
                        product_id=item.product_id,
                        qty=item.qty,
                        unit_sell_price=unit_price,
                        line_total=line_total,
                    )
                    self.db.add(sales_item)
                    sales_items.append(sales_item)

                    balance.on_hand_qty -= item.qty
                    balance.last_movement_at = timestamp

                    movement = StockMovement(
                        product_id=item.product_id,
                        movement_type="sale",
                        qty_delta=-item.qty,
                        unit_price=unit_price,
                        reason="sale",
                        reference_type="sales_transaction",
                        reference_id=transaction.id,
                        occurred_at=timestamp,
                    )
                    self.db.add(movement)

                transaction.total_amount = total_amount

            return SaleRead(
                id=transaction.id,
                receipt_no=transaction.receipt_no,
                sold_at=transaction.sold_at,
                total_amount=transaction.total_amount,
                payment_method=transaction.payment_method,
                items=[
                    SaleItemRead(
                        id=item.id,
                        product_id=item.product_id,
                        qty=item.qty,
                        unit_sell_price=item.unit_sell_price,
                        line_total=item.line_total,
                    )
                    for item in sales_items
                ],
            )
        except HTTPException:
            self.db.rollback()
            raise

