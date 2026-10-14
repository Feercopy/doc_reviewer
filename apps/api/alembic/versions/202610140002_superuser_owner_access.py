"""Add revocable owner scopes for SuperUser accounts."""

from alembic import op
import sqlalchemy as sa


revision = "202610140002"
down_revision = "202610140001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "superuser_owner_access",
        sa.Column("superuser_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("granted_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_superuser_owner_access_owner_id", "superuser_owner_access", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_superuser_owner_access_owner_id", table_name="superuser_owner_access")
    op.drop_table("superuser_owner_access")
