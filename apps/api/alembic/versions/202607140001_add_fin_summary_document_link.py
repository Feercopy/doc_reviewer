"""add_fin_summary_document_link

Revision ID: 202607140001
Revises: 202607090001
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "202607140001"
down_revision: Union[str, None] = "202607090001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("linked_fin_summary_document_id", sa.Uuid(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("document_role", sa.String(), nullable=False, server_default="primary"),
    )
    op.create_foreign_key(
        "fk_documents_linked_fin_summary_document_id_documents",
        "documents",
        "documents",
        ["linked_fin_summary_document_id"],
        ["id"],
    )
    op.create_index(
        "ix_documents_linked_fin_summary_document_id",
        "documents",
        ["linked_fin_summary_document_id"],
        unique=False,
    )
    op.create_index("ix_documents_document_role", "documents", ["document_role"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_document_role", table_name="documents")
    op.drop_index("ix_documents_linked_fin_summary_document_id", table_name="documents")
    op.drop_constraint("fk_documents_linked_fin_summary_document_id_documents", "documents", type_="foreignkey")
    op.drop_column("documents", "document_role")
    op.drop_column("documents", "linked_fin_summary_document_id")
