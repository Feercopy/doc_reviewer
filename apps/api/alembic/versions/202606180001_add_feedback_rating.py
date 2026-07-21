"""add feedback rating

Revision ID: 202606180001
Revises: 202606170002
Create Date: 2026-06-18 00:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "202606180001"
down_revision: str | None = "202606170002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("rating", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback", "rating")
