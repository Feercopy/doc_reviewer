"""add external skill source snapshots

Revision ID: 202606080002
Revises: 202606080001
Create Date: 2026-06-08 19:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "202606080002"
down_revision: str | None = "202606080001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("local_path", sa.String(), nullable=True),
        sa.Column("repo_url", sa.String(), nullable=True),
        sa.Column("default_ref", sa.String(), nullable=True),
        sa.Column("entrypoint", sa.String(), nullable=False),
        sa.Column("required_paths", sa.JSON(), nullable=False),
        sa.Column("update_policy", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "skill_source_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_source_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=True),
        sa.Column("predicted_comment_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_slug", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=True),
        sa.Column("repo_url", sa.String(), nullable=True),
        sa.Column("requested_ref", sa.String(), nullable=True),
        sa.Column("resolved_revision", sa.String(), nullable=True),
        sa.Column("is_dirty", sa.Boolean(), nullable=False),
        sa.Column("dirty_details", sa.JSON(), nullable=False),
        sa.Column("snapshot_mode", sa.String(), nullable=False),
        sa.Column("source_fingerprint", sa.String(), nullable=False),
        sa.Column("file_manifest", sa.JSON(), nullable=False),
        sa.Column("artifact_path", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(analysis_id IS NOT NULL AND predicted_comment_run_id IS NULL) "
            "OR (analysis_id IS NULL AND predicted_comment_run_id IS NOT NULL)",
            name="ck_skill_source_snapshots_one_owner",
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["predicted_comment_run_id"], ["predicted_comment_runs.id"]),
        sa.ForeignKeyConstraint(["skill_source_id"], ["skill_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "retrieval_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("predicted_comment_run_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_mode", sa.String(), nullable=False),
        sa.Column("retrieval_version", sa.String(), nullable=False),
        sa.Column("corpus_fingerprint", sa.String(), nullable=False),
        sa.Column("query_fingerprint", sa.String(), nullable=False),
        sa.Column("selected_items", sa.JSON(), nullable=False),
        sa.Column("artifact_path", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["predicted_comment_run_id"], ["predicted_comment_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("skills", sa.Column("skill_source_id", sa.Uuid(), nullable=True))
    op.add_column("skills", sa.Column("runtime_mode", sa.String(), nullable=False, server_default="snapshot_required"))
    op.create_foreign_key("fk_skills_skill_source_id", "skills", "skill_sources", ["skill_source_id"], ["id"])
    op.alter_column("skills", "runtime_mode", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_skills_skill_source_id", "skills", type_="foreignkey")
    op.drop_column("skills", "runtime_mode")
    op.drop_column("skills", "skill_source_id")
    op.drop_table("retrieval_snapshots")
    op.drop_table("skill_source_snapshots")
    op.drop_table("skill_sources")
