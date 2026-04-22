from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from math import ceil
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.db.models import AdminUser, InventoryBalance, Product, SalesItem, SalesTransaction, StockMovement
from app.schemas.sales import SaleCreate, SaleItemRead, SaleRead, SaleTransactionLineRead, SaleTransactionPageRead


class SalesService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_sales(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        sort: str = "desc",
        page: int = 1,
        page_size: int = 50,
    ) -> SaleTransactionPageRead:
        filters = []
        if date_from is not None:
            filters.append(SalesTransaction.sold_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
        if date_to is not None:
            filters.append(
                SalesTransaction.sold_at
                < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
            )

        count_statement = (
            select(func.count(SalesItem.id))
            .join(SalesTransaction, SalesItem.sales_transaction_id == SalesTransaction.id)
            .join(Product, Product.id == SalesItem.product_id)
        )
        if filters:
            count_statement = count_statement.where(*filters)

        total = int(self.db.scalar(count_statement) or 0)
        total_pages = max(1, ceil(total / page_size))
        offset = (page - 1) * page_size

        statement = (
            select(SalesTransaction, SalesItem, Product)
            .join(SalesItem, SalesItem.sales_transaction_id == SalesTransaction.id)
            .join(Product, Product.id == SalesItem.product_id)
        )
        if filters:
            statement = statement.where(*filters)

        order_direction = asc if sort == "asc" else desc
        statement = statement.order_by(
            order_direction(SalesTransaction.sold_at),
            order_direction(SalesTransaction.id),
            order_direction(SalesItem.id),
        ).limit(page_size).offset(offset)

        items = [
            SaleTransactionLineRead(
                transaction_id=transaction.id,
                item_id=item.id,
                receipt_no=transaction.receipt_no,
                sold_at=transaction.sold_at,
                product_id=product.id,
                sku=product.sku,
                product_name=product.name,
                qty=item.qty,
                unit_sell_price=item.unit_sell_price,
                line_total=item.line_total,
                total_amount=transaction.total_amount,
                payment_method=transaction.payment_method,
                ordered_by_username=transaction.ordered_by_username,
            )
            for transaction, item, product in self.db.execute(statement).all()
        ]
        return SaleTransactionPageRead(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def create_sale(self, payload: SaleCreate, actor: AdminUser | None = None) -> SaleRead:
        timestamp = payload.sold_at or datetime.now(timezone.utc)
        receipt_no = payload.receipt_no or f"R-{uuid4().hex[:12].upper()}"

        try:
            transaction = SalesTransaction(
                receipt_no=receipt_no,
                sold_at=timestamp,
                total_amount=Decimal("0.00"),
                payment_method=payload.payment_method,
                ordered_by_username=actor.username if actor is not None else None,
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
            self.db.commit()

            return SaleRead(
                id=transaction.id,
                receipt_no=transaction.receipt_no,
                sold_at=transaction.sold_at,
                total_amount=transaction.total_amount,
                payment_method=transaction.payment_method,
                ordered_by_username=transaction.ordered_by_username,
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
        except Exception:
            self.db.rollback()
            raise
