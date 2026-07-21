"""add provider model allowlist

Revision ID: 202606140001
Revises: 202606080002
Create Date: 2026-06-14 15:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "202606140001"
down_revision: str | None = "202606080002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_OPENAI_COMPATIBLE_MODELS = [
    "anthropic/claude-opus-4.7",
    "anthropic/claude-sonnet-4.6",
    "deepseek/deepseek-v4-pro",
    "google/gemini-3.5-flash",
    "openai/gpt-5.5",
    "qwen/qwen3.5-397b-a17b",
]
DEFAULT_OPENAI_COMPATIBLE_MODEL = "google/gemini-3.5-flash"


def upgrade() -> None:
    op.add_column("provider_keys", sa.Column("available_models", sa.JSON(), nullable=True))
    connection = op.get_bind()
    provider_keys = sa.table(
        "provider_keys",
        sa.column("provider", sa.String()),
        sa.column("default_model", sa.String()),
        sa.column("available_models", sa.JSON()),
    )
    rows = connection.execute(sa.select(provider_keys.c.provider, provider_keys.c.default_model)).all()
    for provider, default_model in rows:
        if provider == "openai_compatible":
            models = list(DEFAULT_OPENAI_COMPATIBLE_MODELS)
            next_default_model = default_model if default_model in models else DEFAULT_OPENAI_COMPATIBLE_MODEL
        else:
            models = [default_model]
            next_default_model = default_model
        connection.execute(
            provider_keys.update()
            .where(provider_keys.c.provider == provider, provider_keys.c.default_model == default_model)
            .values(default_model=next_default_model, available_models=models)
        )
    op.alter_column("provider_keys", "available_models", nullable=False)


def downgrade() -> None:
    op.drop_column("provider_keys", "available_models")
