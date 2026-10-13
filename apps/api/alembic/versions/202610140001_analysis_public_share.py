"""Add revocable public analysis share links."""

from alembic import op
import sqlalchemy as sa


revision = "202610140001"
down_revision = "202609170001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("public_share_nonce", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "public_share_nonce")
