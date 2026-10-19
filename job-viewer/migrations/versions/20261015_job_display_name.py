"""Add optional job.name display label.

Revision ID: 20261015_name
Revises: 20261015_params
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261015_name"
down_revision = "20261015_params"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    job_cols = _columns("job")
    if job_cols and "name" not in job_cols:
        with op.batch_alter_table("job") as batch:
            batch.add_column(sa.Column("name", sa.String(length=200), nullable=True))


def downgrade() -> None:
    job_cols = _columns("job")
    if job_cols and "name" in job_cols:
        with op.batch_alter_table("job") as batch:
            batch.drop_column("name")
