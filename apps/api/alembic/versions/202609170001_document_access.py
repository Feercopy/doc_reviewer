"""Add explicit read-only document access grants."""

from alembic import op
import sqlalchemy as sa


revision = "202609170001"
down_revision = "202607140001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_access",
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("granted_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_access_user_id", "document_access", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_document_access_user_id", table_name="document_access")
    op.drop_table("document_access")
