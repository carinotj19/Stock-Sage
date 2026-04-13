from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(120))
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="admin", server_default="admin")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    actor_username: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[Optional[int]] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(120))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    lead_time_days_default: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    products: Mapped[list["Product"]] = relationship(back_populates="supplier")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(120))
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    cost_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    sell_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    reorder_min_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reorder_multiple: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    supplier: Mapped[Optional[Supplier]] = relationship(back_populates="products")
    inventory_balance: Mapped[Optional["InventoryBalance"]] = relationship(back_populates="product", uselist=False)
    stock_movements: Mapped[list["StockMovement"]] = relationship(back_populates="product")


class InventoryBalance(Base):
    __tablename__ = "inventory_balance"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    on_hand_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_movement_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    product: Mapped["Product"] = relationship(back_populates="inventory_balance")


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (Index("ix_stock_movements_product_id_occurred_at", "product_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(50), nullable=False)
    qty_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    reference_type: Mapped[Optional[str]] = mapped_column(String(50))
    reference_id: Mapped[Optional[int]] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product: Mapped["Product"] = relationship(back_populates="stock_movements")


class SalesTransaction(Base):
    __tablename__ = "sales_transactions"
    __table_args__ = (Index("ix_sales_transactions_sold_at", "sold_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_no: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items: Mapped[list["SalesItem"]] = relationship(back_populates="transaction")


class SalesItem(Base):
    __tablename__ = "sales_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("sales_transactions.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_sell_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    transaction: Mapped["SalesTransaction"] = relationship(back_populates="items")


class CompetitorSource(Base):
    __tablename__ = "competitor_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    scrape_config_json: Mapped[Optional[str]] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CompetitorPriceSnapshot(Base):
    __tablename__ = "competitor_price_snapshots"
    __table_args__ = (Index("ix_competitor_price_snapshots_product_id_scraped_at", "product_id", "scraped_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("competitor_sources.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    competitor_sku: Mapped[Optional[str]] = mapped_column(String(120))
    competitor_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="PHP")
    in_stock: Mapped[Optional[bool]] = mapped_column(Boolean)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    raw_payload_json: Mapped[Optional[str]] = mapped_column(Text)


class ForecastRun(Base):
    __tablename__ = "forecast_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    model_version: Mapped[Optional[str]] = mapped_column(String(100))
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class SkuForecast(Base):
    __tablename__ = "sku_forecasts"
    __table_args__ = (Index("ix_sku_forecasts_product_id_forecast_date", "product_id", "forecast_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    predicted_units: Mapped[float] = mapped_column(nullable=False)
    lower_ci: Mapped[Optional[float]] = mapped_column()
    upper_ci: Mapped[Optional[float]] = mapped_column()


class ReorderRecommendation(Base):
    __tablename__ = "reorder_recommendations"
    __table_args__ = (Index("ix_reorder_recommendations_product_id_created_at", "product_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    predicted_stockout_date: Mapped[Optional[date]] = mapped_column(Date)
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False)
    suggested_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_score: Mapped[Optional[float]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
