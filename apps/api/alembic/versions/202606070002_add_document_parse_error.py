"""add document parse error

Revision ID: 202606070002
Revises: 202606070001
Create Date: 2026-06-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "202606070002"
down_revision: str | None = "202606070001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("parse_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "parse_error")
