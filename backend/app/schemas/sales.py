from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SaleItemCreate(BaseModel):
    product_id: int
    qty: int = Field(ge=1)
    unit_sell_price: Decimal | None = Field(default=None, ge=0)


class SaleCreate(BaseModel):
    receipt_no: str | None = Field(default=None, max_length=64)
    sold_at: datetime | None = None
    payment_method: str | None = Field(default=None, max_length=50)
    ordered_by_username: str | None = Field(default=None, max_length=100)
    items: list[SaleItemCreate] = Field(min_length=1)


class SaleItemRead(BaseModel):
    id: int
    product_id: int
    qty: int
    unit_sell_price: Decimal
    line_total: Decimal


class SaleRead(BaseModel):
    id: int
    receipt_no: str
    sold_at: datetime
    total_amount: Decimal
    payment_method: str | None
    ordered_by_username: str | None = None
    items: list[SaleItemRead]


class SaleTransactionLineRead(BaseModel):
    transaction_id: int
    item_id: int
    receipt_no: str
    sold_at: datetime
    product_id: int
    sku: str
    product_name: str
    qty: int
    unit_sell_price: Decimal
    line_total: Decimal
    total_amount: Decimal
    payment_method: str | None
    ordered_by_username: str | None = None


class SaleTransactionPageRead(BaseModel):
    items: list[SaleTransactionLineRead]
    total: int
    page: int
    page_size: int
    total_pages: int
