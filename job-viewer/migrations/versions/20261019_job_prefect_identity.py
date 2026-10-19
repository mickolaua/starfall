"""Add prefect_idempotency_key and prefect_flow_run_id on job.

Revision ID: 20261019_prefect
Revises: 20261015_name
Create Date: 2026-10-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261019_prefect"
down_revision = "20261015_name"
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
    if not job_cols:
        return
    with op.batch_alter_table("job") as batch:
        if "prefect_idempotency_key" not in job_cols:
            batch.add_column(
                sa.Column("prefect_idempotency_key", sa.String(length=120), nullable=True)
            )
        if "prefect_flow_run_id" not in job_cols:
            batch.add_column(
                sa.Column("prefect_flow_run_id", sa.String(length=64), nullable=True)
            )


def downgrade() -> None:
    job_cols = _columns("job")
    if not job_cols:
        return
    with op.batch_alter_table("job") as batch:
        if "prefect_flow_run_id" in job_cols:
            batch.drop_column("prefect_flow_run_id")
        if "prefect_idempotency_key" in job_cols:
            batch.drop_column("prefect_idempotency_key")
