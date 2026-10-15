"""Add job_parameters Text, started_at/finished_at; ensure user API token columns.

Revision ID: 20261015_params
Revises:
Create Date: 2026-10-15

Idempotent: only adds columns that are missing (safe for DBs that already had
partial schema from ensure_* helpers).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261015_params"
down_revision = None
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
    if job_cols:
        with op.batch_alter_table("job") as batch:
            if "job_parameters" not in job_cols:
                batch.add_column(sa.Column("job_parameters", sa.Text(), nullable=True))
            if "started_at" not in job_cols:
                batch.add_column(
                    sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
                )
            if "finished_at" not in job_cols:
                batch.add_column(
                    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True)
                )

    user_cols = _columns("user")
    if user_cols:
        with op.batch_alter_table("user") as batch:
            if "api_token_hash" not in user_cols:
                batch.add_column(
                    sa.Column("api_token_hash", sa.String(length=255), nullable=True)
                )
            if "api_token_prefix" not in user_cols:
                batch.add_column(
                    sa.Column("api_token_prefix", sa.String(length=16), nullable=True)
                )


def downgrade() -> None:
    job_cols = _columns("job")
    if job_cols:
        with op.batch_alter_table("job") as batch:
            if "finished_at" in job_cols:
                batch.drop_column("finished_at")
            if "started_at" in job_cols:
                batch.drop_column("started_at")
            # Keep job_parameters on downgrade if it pre-existed; only drop if we
            # cannot know. Prefer leaving the column.
            pass

    user_cols = _columns("user")
    if user_cols:
        with op.batch_alter_table("user") as batch:
            if "api_token_prefix" in user_cols:
                batch.drop_column("api_token_prefix")
            if "api_token_hash" in user_cols:
                batch.drop_column("api_token_hash")
