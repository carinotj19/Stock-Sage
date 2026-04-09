from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    lead_time_days_default: int = Field(default=7, ge=0)


class SupplierRead(BaseModel):
    id: int
    name: str
    contact_name: str | None
    phone: str | None
    email: str | None
    lead_time_days_default: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=120)
    supplier_id: int | None = None
    cost_price: Decimal = Field(default=Decimal("0.00"), ge=0)
    sell_price: Decimal = Field(default=Decimal("0.00"), ge=0)
    reorder_min_qty: int = Field(default=1, ge=1)
    reorder_multiple: int = Field(default=1, ge=1)
    safety_stock: int = Field(default=0, ge=0)
    active: bool = True
    initial_stock: int = Field(default=0, ge=0)


class ProductRead(BaseModel):
    id: int
    sku: str
    name: str
    category: str | None
    supplier_id: int | None
    cost_price: Decimal
    sell_price: Decimal
    reorder_min_qty: int
    reorder_multiple: int
    safety_stock: int
    active: bool
    on_hand_qty: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductUpdate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    sell_price: Decimal = Field(ge=0)
    safety_stock: int = Field(ge=0)
    on_hand_qty: int = Field(ge=0)


class InventoryAdjustRequest(BaseModel):
    product_id: int
    qty_delta: int
    reason: str | None = Field(default=None, max_length=255)
    reference_type: str | None = Field(default=None, max_length=50)
    reference_id: int | None = None
    unit_price: Decimal | None = Field(default=None, ge=0)


class InventoryAdjustResponse(BaseModel):
    product_id: int
    on_hand_qty: int
    last_movement_at: datetime | None
