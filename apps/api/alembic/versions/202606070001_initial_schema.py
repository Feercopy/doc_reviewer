"""initial_schema

Revision ID: 202606070001
Revises:
Create Date: 2026-06-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "202606070001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("login", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login"),
    )
    op.create_index("ix_users_login", "users", ["login"], unique=False)

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_hash_sha256", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("parse_status", sa.String(), nullable=False),
        sa.Column("detected_document_type", sa.String(), nullable=False),
        sa.Column("document_type_confidence", sa.Numeric(), nullable=True),
        sa.Column("document_type_explanation", sa.Text(), nullable=True),
        sa.Column("manual_document_type", sa.String(), nullable=True),
        sa.Column("parsed_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_owner_created_at", "documents", ["owner_id", "created_at"], unique=False)
    op.create_index("ix_documents_file_hash_sha256", "documents", ["file_hash_sha256"], unique=False)
    op.create_index("ix_documents_detected_document_type", "documents", ["detected_document_type"], unique=False)

    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("skill_type", sa.String(), nullable=False),
        sa.Column("supported_document_types", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_uri", sa.String(), nullable=True),
        sa.Column("source_entrypoint", sa.String(), nullable=True),
        sa.Column("source_revision", sa.String(), nullable=True),
        sa.Column("source_fingerprint", sa.String(), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("result_schema_path", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", "skill_type", name="uq_skills_name_version_type"),
    )

    op.create_table(
        "analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("skill_version", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("verdict", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(), nullable=True),
        sa.Column("run_parameters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analyses_document_created_at", "analyses", ["document_id", "created_at"], unique=False)
    op.create_index("ix_analyses_user_created_at", "analyses", ["user_id", "created_at"], unique=False)
    op.create_index("ix_analyses_provider_model", "analyses", ["provider", "model"], unique=False)
    op.create_index("ix_analyses_skill_version", "analyses", ["skill_id", "skill_version"], unique=False)

    op.create_table(
        "predicted_comment_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("skill_version", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "etalons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("real_defense_status", sa.String(), nullable=True),
        sa.Column("defense_comments", sa.Text(), nullable=True),
        sa.Column("expected_verdict", sa.String(), nullable=False),
        sa.Column("layer_1", sa.JSON(), nullable=False),
        sa.Column("layer_2", sa.JSON(), nullable=False),
        sa.Column("key_findings", sa.JSON(), nullable=False),
        sa.Column("forbidden_false_findings", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("raw_file_visible_to_all", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "benchmarks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("etalon_ids", sa.JSON(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("skill_version", sa.String(), nullable=False),
        sa.Column("judge_skill_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_by_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overall_score", sa.Numeric(), nullable=True),
        sa.Column("layer_1_score", sa.Numeric(), nullable=True),
        sa.Column("layer_2_score", sa.Numeric(), nullable=True),
        sa.Column("precision", sa.Numeric(), nullable=True),
        sa.Column("recall", sa.Numeric(), nullable=True),
        sa.Column("f1", sa.Numeric(), nullable=True),
        sa.Column("missed_findings", sa.JSON(), nullable=True),
        sa.Column("false_positives", sa.JSON(), nullable=True),
        sa.Column("partial_matches", sa.JSON(), nullable=True),
        sa.Column("judge_output", sa.JSON(), nullable=True),
        sa.Column("run_parameters", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["judge_skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["started_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("skill_version", sa.String(), nullable=False),
        sa.Column("usefulness", sa.String(), nullable=False),
        sa.Column("verdict_correct", sa.Boolean(), nullable=True),
        sa.Column("has_false_findings", sa.Boolean(), nullable=True),
        sa.Column("has_missed_findings", sa.Boolean(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("can_use_for_benchmark", sa.Boolean(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "provider_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("default_model", sa.String(), nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary(), nullable=False),
        sa.Column("api_key_fingerprint", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "provider", name="uq_provider_keys_owner_provider"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("provider_keys")
    op.drop_table("feedback")
    op.drop_table("benchmarks")
    op.drop_table("etalons")
    op.drop_table("predicted_comment_runs")
    op.drop_index("ix_analyses_skill_version", table_name="analyses")
    op.drop_index("ix_analyses_provider_model", table_name="analyses")
    op.drop_index("ix_analyses_user_created_at", table_name="analyses")
    op.drop_index("ix_analyses_document_created_at", table_name="analyses")
    op.drop_table("analyses")
    op.drop_table("skills")
    op.drop_index("ix_documents_detected_document_type", table_name="documents")
    op.drop_index("ix_documents_file_hash_sha256", table_name="documents")
    op.drop_index("ix_documents_owner_created_at", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_users_login", table_name="users")
    op.drop_table("users")
