"""add benchmark report

Revision ID: 202606080001
Revises: 202606070003
Create Date: 2026-06-08 12:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "202606080001"
down_revision: str | None = "202606070003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("benchmarks", sa.Column("report", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("benchmarks", "report")
