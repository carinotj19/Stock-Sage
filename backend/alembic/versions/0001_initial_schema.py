"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-11 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("lead_time_days_default", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("cost_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("sell_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("reorder_min_qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reorder_multiple", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("safety_stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)

    op.create_table(
        "inventory_balance",
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("on_hand_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_movement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("product_id"),
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("movement_type", sa.String(length=50), nullable=False),
        sa.Column("qty_delta", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("reference_type", sa.String(length=50), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_stock_movements_product_id_occurred_at",
        "stock_movements",
        ["product_id", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "sales_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("receipt_no", sa.String(length=64), nullable=False, unique=True),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("payment_method", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_sales_transactions_sold_at", "sales_transactions", ["sold_at"], unique=False)

    op.create_table(
        "sales_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sales_transaction_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_sell_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(10, 2), nullable=False),
        sa.ForeignKeyConstraint(["sales_transaction_id"], ["sales_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
    )

    op.create_table(
        "competitor_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("scrape_config_json", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "competitor_price_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("competitor_sku", sa.String(length=120), nullable=True),
        sa.Column("competitor_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="PHP"),
        sa.Column("in_stock", sa.Boolean(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["competitor_sources.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_competitor_price_snapshots_product_id_scraped_at",
        "competitor_price_snapshots",
        ["product_id", "scraped_at"],
        unique=False,
    )

    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("model_version", sa.String(length=100), nullable=True),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "sku_forecasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("predicted_units", sa.Float(), nullable=False),
        sa.Column("lower_ci", sa.Float(), nullable=True),
        sa.Column("upper_ci", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sku_forecasts_product_id_forecast_date", "sku_forecasts", ["product_id", "forecast_date"])

    op.create_table(
        "reorder_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("predicted_stockout_date", sa.Date(), nullable=True),
        sa.Column("reorder_point", sa.Integer(), nullable=False),
        sa.Column("suggested_qty", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_reorder_recommendations_product_id_created_at",
        "reorder_recommendations",
        ["product_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reorder_recommendations_product_id_created_at", table_name="reorder_recommendations")
    op.drop_table("reorder_recommendations")
    op.drop_index("ix_sku_forecasts_product_id_forecast_date", table_name="sku_forecasts")
    op.drop_table("sku_forecasts")
    op.drop_table("forecast_runs")
    op.drop_index(
        "ix_competitor_price_snapshots_product_id_scraped_at",
        table_name="competitor_price_snapshots",
    )
    op.drop_table("competitor_price_snapshots")
    op.drop_table("competitor_sources")
    op.drop_table("sales_items")
    op.drop_index("ix_sales_transactions_sold_at", table_name="sales_transactions")
    op.drop_table("sales_transactions")
    op.drop_index("ix_stock_movements_product_id_occurred_at", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_table("inventory_balance")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_table("products")
    op.drop_table("suppliers")
