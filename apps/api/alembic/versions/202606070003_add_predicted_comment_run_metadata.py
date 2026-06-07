"""add predicted comment run metadata

Revision ID: 202606070003
Revises: 202606070002
Create Date: 2026-06-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "202606070003"
down_revision: str | None = "202606070002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("predicted_comment_runs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("predicted_comment_runs", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column("predicted_comment_runs", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("predicted_comment_runs", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("predicted_comment_runs", sa.Column("estimated_cost", sa.Numeric(), nullable=True))
    op.add_column(
        "predicted_comment_runs",
        sa.Column("run_parameters", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("predicted_comment_runs", "run_parameters")
    op.drop_column("predicted_comment_runs", "estimated_cost")
    op.drop_column("predicted_comment_runs", "output_tokens")
    op.drop_column("predicted_comment_runs", "input_tokens")
    op.drop_column("predicted_comment_runs", "latency_ms")
    op.drop_column("predicted_comment_runs", "started_at")
