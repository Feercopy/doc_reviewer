"""add ic agentic review run tables

Revision ID: 202607090001
Revises: 202606180001
Create Date: 2026-07-09 00:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "202607090001"
down_revision: str | None = "202606180001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


THREE_OWNER_CHECK = (
    "((CASE WHEN analysis_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN predicted_comment_run_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN analysis_check_run_id IS NOT NULL THEN 1 ELSE 0 END)) = 1"
)

TWO_OWNER_CHECK = (
    "(analysis_id IS NOT NULL AND predicted_comment_run_id IS NULL) "
    "OR (analysis_id IS NULL AND predicted_comment_run_id IS NOT NULL)"
)


def upgrade() -> None:
    op.create_table(
        "analysis_check_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("skill_version", sa.String(), nullable=False),
        sa.Column("check_type", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_stage", sa.String(), nullable=True),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("legacy_output", sa.JSON(), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(), nullable=True),
        sa.Column("run_parameters", sa.JSON(), nullable=False),
        sa.Column("artifacts", sa.JSON(), nullable=False),
        sa.Column("uploaded_workbook_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_check_runs_analysis_created_at",
        "analysis_check_runs",
        ["analysis_id", "created_at"],
    )
    op.create_index(
        "ix_analysis_check_runs_status_created_at",
        "analysis_check_runs",
        ["status", "created_at"],
    )

    op.create_table(
        "analysis_check_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("check_run_id", sa.Uuid(), nullable=False),
        sa.Column("step_type", sa.String(), nullable=False),
        sa.Column("step_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("prompt_fingerprint", sa.String(), nullable=True),
        sa.Column("prompt_artifact_path", sa.String(), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(), nullable=True),
        sa.Column("artifacts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["check_run_id"], ["analysis_check_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_check_steps_run_step_name",
        "analysis_check_steps",
        ["check_run_id", "step_name"],
    )

    with op.batch_alter_table("skill_source_snapshots") as batch_op:
        batch_op.drop_constraint("ck_skill_source_snapshots_one_owner", type_="check")
        batch_op.add_column(sa.Column("analysis_check_run_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_skill_source_snapshots_analysis_check_run_id",
            "analysis_check_runs",
            ["analysis_check_run_id"],
            ["id"],
        )
        batch_op.create_check_constraint("ck_skill_source_snapshots_one_owner", THREE_OWNER_CHECK)


def downgrade() -> None:
    # The previous schema cannot represent snapshots owned only by IC review runs.
    op.execute("DELETE FROM skill_source_snapshots WHERE analysis_check_run_id IS NOT NULL")
    with op.batch_alter_table("skill_source_snapshots") as batch_op:
        batch_op.drop_constraint("ck_skill_source_snapshots_one_owner", type_="check")
        batch_op.drop_constraint("fk_skill_source_snapshots_analysis_check_run_id", type_="foreignkey")
        batch_op.drop_column("analysis_check_run_id")
        batch_op.create_check_constraint("ck_skill_source_snapshots_one_owner", TWO_OWNER_CHECK)

    op.drop_index("ix_analysis_check_steps_run_step_name", table_name="analysis_check_steps")
    op.drop_table("analysis_check_steps")
    op.drop_index("ix_analysis_check_runs_status_created_at", table_name="analysis_check_runs")
    op.drop_index("ix_analysis_check_runs_analysis_created_at", table_name="analysis_check_runs")
    op.drop_table("analysis_check_runs")
