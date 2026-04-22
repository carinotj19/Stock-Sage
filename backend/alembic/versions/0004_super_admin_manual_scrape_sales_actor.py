"""add super admin support and sales actor

Revision ID: 0004_super_admin_sales_actor
Revises: 0003_user_roles_audit_logs
Create Date: 2026-04-22 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_super_admin_sales_actor"
down_revision: Union[str, None] = "0003_user_roles_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    sales_columns = {column["name"] for column in inspector.get_columns("sales_transactions")}

    if "ordered_by_username" not in sales_columns:
        op.add_column("sales_transactions", sa.Column("ordered_by_username", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("sales_transactions", "ordered_by_username")
