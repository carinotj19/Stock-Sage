"""add user roles and audit logs

Revision ID: 0003_user_roles_audit_logs
Revises: 0002_admin_users
Create Date: 2026-04-14 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_user_roles_audit_logs"
down_revision: Union[str, None] = "0002_admin_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    admin_columns = {column["name"] for column in inspector.get_columns("admin_users")}

    if "display_name" not in admin_columns:
        op.add_column("admin_users", sa.Column("display_name", sa.String(length=120), nullable=True))
    if "email" not in admin_columns:
        op.add_column("admin_users", sa.Column("email", sa.String(length=255), nullable=True))
    if "role" not in admin_columns:
        op.add_column(
            "admin_users",
            sa.Column("role", sa.String(length=20), nullable=False, server_default=sa.text("'admin'")),
        )

    admin_indexes = {index["name"] for index in inspector.get_indexes("admin_users")}
    if "ix_admin_users_email" not in admin_indexes:
        op.create_index("ix_admin_users_email", "admin_users", ["email"], unique=True)
    op.execute("UPDATE admin_users SET display_name = username WHERE display_name IS NULL")

    table_names = set(inspector.get_table_names())
    if "audit_logs" not in table_names:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_username", sa.String(length=100), nullable=False),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column("target_type", sa.String(length=80), nullable=False),
            sa.Column("target_id", sa.Integer(), nullable=True),
            sa.Column("message", sa.String(length=500), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    inspector = sa.inspect(bind)
    audit_indexes = {index["name"] for index in inspector.get_indexes("audit_logs")}
    if "ix_audit_logs_created_at" not in audit_indexes:
        op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_admin_users_email", table_name="admin_users")
    op.drop_column("admin_users", "role")
    op.drop_column("admin_users", "email")
    op.drop_column("admin_users", "display_name")
