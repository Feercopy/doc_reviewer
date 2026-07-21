"""add analysis detail runs

Revision ID: 202606140002
Revises: 202606140001
Create Date: 2026-06-14 18:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "202606140002"
down_revision: str | None = "202606140001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_detail_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("previous_response_id", sa.Text(), nullable=True),
        sa.Column("response_id", sa.Text(), nullable=True),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(), nullable=True),
        sa.Column("run_parameters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_detail_runs_analysis_created_at",
        "analysis_detail_runs",
        ["analysis_id", "created_at"],
    )
    op.create_index(
        "ix_analysis_detail_runs_status_created_at",
        "analysis_detail_runs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_analysis_detail_runs_provider_model",
        "analysis_detail_runs",
        ["provider", "model"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_detail_runs_provider_model", table_name="analysis_detail_runs")
    op.drop_index("ix_analysis_detail_runs_status_created_at", table_name="analysis_detail_runs")
    op.drop_index("ix_analysis_detail_runs_analysis_created_at", table_name="analysis_detail_runs")
    op.drop_table("analysis_detail_runs")
