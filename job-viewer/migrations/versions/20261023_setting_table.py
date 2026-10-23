"""Add setting key/value table for site config.

Revision ID: 20261023_setting
Revises: 20261019_prefect
Create Date: 2026-10-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261023_setting"
down_revision = "20261019_prefect"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "setting" in inspector.get_table_names():
        return
    op.create_table(
        "setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
    )
    op.create_index("ix_setting_key", "setting", ["key"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "setting" not in inspector.get_table_names():
        return
    op.drop_index("ix_setting_key", table_name="setting")
    op.drop_table("setting")
